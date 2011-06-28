# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Rate limiting of arbitrary actions."""

import httplib
import time
import urllib
import webob.dec
import webob.exc

from nova import wsgi
from nova.api.openstack import faults

# Convenience constants for the limits dictionary passed to Limiter().
PER_SECOND = 1
PER_MINUTE = 60
PER_HOUR = 60 * 60
PER_DAY = 60 * 60 * 24


class RateLimitingMiddleware(wsgi.Middleware):
    """Rate limit incoming requests according to the OpenStack rate limits."""

    def __init__(self, application, service_host=None):
        """Create a rate limiting middleware that wraps the given application.

        By default, rate counters are stored in memory.  If service_host is
        specified, the middleware instead relies on the ratelimiting.WSGIApp
        at the given host+port to keep rate counters.
        """
        if not service_host:
            #TODO(gundlach): These limits were based on limitations of Cloud
            #Servers.  We should revisit them in Nova.
            self.limiter = Limiter(limits={
                    'DELETE': (100, PER_MINUTE),
                    'PUT': (10, PER_MINUTE),
                    'POST': (10, PER_MINUTE),
                    'POST servers': (50, PER_DAY),
                    'GET changes-since': (3, PER_MINUTE),
                })
        else:
            self.limiter = WSGIAppProxy(service_host)
        super(RateLimitingMiddleware, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Rate limit the request.

        If the request should be rate limited, return a 413 status with a
        Retry-After header giving the time when the request would succeed.
        """
        return self.rate_limited_request(req, self.application)

    def rate_limited_request(self, req, application):
        """Rate limit the request.

        If the request should be rate limited, return a 413 status with a
        Retry-After header giving the time when the request would succeed.
        """
        action_name = self.get_action_name(req)
        if not action_name:
            # Not rate limited
            return application
        delay = self.get_delay(action_name,
            req.environ['nova.context'].user_id)
        if delay:
            # TODO(gundlach): Get the retry-after format correct.
            exc = webob.exc.HTTPRequestEntityTooLarge(
                    explanation=('Too many requests.'),
                    headers={'Retry-After': time.time() + delay})
            raise faults.Fault(exc)
        return application

    def get_delay(self, action_name, username):
        """Return the delay for the given action and username, or None if
        the action would not be rate limited.
        """
        if action_name == 'POST servers':
            # "POST servers" is a POST, so it counts against "POST" too.
            # Attempt the "POST" first, lest we are rate limited by "POST" but
            # use up a precious "POST servers" call.
            delay = self.limiter.perform("POST", username=username)
            if delay:
                return delay
        return self.limiter.perform(action_name, username=username)

    def get_action_name(self, req):
        """Return the action name for this request."""
        if req.method == 'GET' and 'changes-since' in req.GET:
            return 'GET changes-since'
        if req.method == 'POST' and req.path_info.startswith('/servers'):
            return 'POST servers'
        if req.method in ['PUT', 'POST', 'DELETE']:
            return req.method
        return None


class Limiter(object):

    """Class providing rate limiting of arbitrary actions."""

    def __init__(self, limits):
        """Create a rate limiter.

        limits: a dict mapping from action name to a tuple.  The tuple contains
        the number of times the action may be performed, and the time period
        (in seconds) during which the number must not be exceeded for this
        action.  Example: dict(reboot=(10, ratelimiting.PER_MINUTE)) would
        allow 10 'reboot' actions per minute.
        """
        self.limits = limits
        self._levels = {}

    def perform(self, action_name, username='nobody'):
        """Attempt to perform an action by the given username.

        action_name: the string name of the action to perform.  This must
        be a key in the limits dict passed to the ctor.

        username: an optional string name of the user performing the action.
        Each user has her own set of rate limiting counters.  Defaults to
        'nobody' (so that if you never specify a username when calling
        perform(), a single set of counters will be used.)

        Return None if the action may proceed.  If the action may not proceed
        because it has been rate limited, return the float number of seconds
        until the action would succeed.
        """
        # Think of rate limiting as a bucket leaking water at 1cc/second.  The
        # bucket can hold as many ccs as there are seconds in the rate
        # limiting period (e.g. 3600 for per-hour ratelimits), and if you can
        # perform N actions in that time, each action fills the bucket by
        # 1/Nth of its volume.  You may only perform an action if the bucket
        # would not overflow.
        now = time.time()
        key = '%s:%s' % (username, action_name)
        last_time_performed, water_level = self._levels.get(key, (now, 0))
        # The bucket leaks 1cc/second.
        water_level -= (now - last_time_performed)
        if water_level < 0:
            water_level = 0
        num_allowed_per_period, period_in_secs = self.limits[action_name]
        # Fill the bucket by 1/Nth its capacity, and hope it doesn't overflow.
        capacity = period_in_secs
        new_level = water_level + (capacity * 1.0 / num_allowed_per_period)
        if new_level > capacity:
            # Delay this many seconds.
            return new_level - capacity
        self._levels[key] = (now, new_level)
        return None

# If one instance of this WSGIApps is unable to handle your load, put a
# sharding app in front that shards by username to one of many backends.


class WSGIApp(object):

    """Application that tracks rate limits in memory.  Send requests to it of
    this form:

    POST /limiter/<username>/<urlencoded action>

    and receive a 200 OK, or a 403 Forbidden with an X-Wait-Seconds header
    containing the number of seconds to wait before the action would succeed.
    """

    def __init__(self, limiter):
        """Create the WSGI application using the given Limiter instance."""
        self.limiter = limiter

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        parts = req.path_info.split('/')
        # format: /limiter/<username>/<urlencoded action>
        if req.method != 'POST':
            raise webob.exc.HTTPMethodNotAllowed()
        if len(parts) != 4 or parts[1] != 'limiter':
            raise webob.exc.HTTPNotFound()
        username = parts[2]
        action_name = urllib.unquote(parts[3])
        delay = self.limiter.perform(action_name, username)
        if delay:
            return webob.exc.HTTPForbidden(
                    headers={'X-Wait-Seconds': "%.2f" % delay})
        else:
            # 200 OK
            return ''


class WSGIAppProxy(object):

    """Limiter lookalike that proxies to a ratelimiting.WSGIApp."""

    def __init__(self, service_host):
        """Creates a proxy pointing to a ratelimiting.WSGIApp at the given
        host."""
        self.service_host = service_host

    def perform(self, action, username='nobody'):
        conn = httplib.HTTPConnection(self.service_host)
        conn.request('POST', '/limiter/%s/%s' % (username, action))
        resp = conn.getresponse()
        if resp.status == 200:
            # No delay
            return None
        return float(resp.getheader('X-Wait-Seconds'))
