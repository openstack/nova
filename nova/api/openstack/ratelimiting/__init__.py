"""Rate limiting of arbitrary actions."""

import httplib
import time
import urllib
import webob.dec
import webob.exc


# Convenience constants for the limits dictionary passed to Limiter().
PER_SECOND = 1
PER_MINUTE = 60
PER_HOUR = 60 * 60
PER_DAY = 60 * 60 * 24


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

    @webob.dec.wsgify
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
