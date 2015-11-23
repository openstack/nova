# Copyright 2011 OpenStack Foundation
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

"""
Module dedicated functions/classes dealing with rate limiting requests.

This module handles rate liming at a per-user level, so it should not be used
to prevent intentional Denial of Service attacks, as we can assume a DOS can
easily come through multiple user accounts. DOS protection should be done at a
different layer.  Instead this module should be used to protect against
unintentional user actions. With that in mind the limits set here should be
high enough as to not rate-limit any intentional actions.

To find good rate-limit values, check how long requests are taking (see logs)
in your environment to assess your capabilities and multiply out to get
figures.

NOTE: As the rate-limiting here is done in memory, this only works per
process (each process will have its own rate limiting counter).
"""

import collections
import copy
import math
import re
import time

from oslo_serialization import jsonutils
from oslo_utils import importutils
from six.moves import http_client as httplib
import webob.dec
import webob.exc

from nova.api.openstack.compute.views import limits as limits_views
from nova.api.openstack import wsgi
from nova.i18n import _
from nova import quota
from nova import utils
from nova import wsgi as base_wsgi


QUOTAS = quota.QUOTAS
LIMITS_PREFIX = "limits."


class LimitsController(object):
    """Controller for accessing limits in the OpenStack API."""

    def index(self, req):
        """Return all global and rate limit information."""
        context = req.environ['nova.context']
        project_id = req.params.get('tenant_id', context.project_id)
        quotas = QUOTAS.get_project_quotas(context, project_id,
                                           usages=False)
        abs_limits = {k: v['limit'] for k, v in quotas.items()}
        rate_limits = req.environ.get("nova.limits", [])

        builder = self._get_view_builder(req)
        return builder.build(rate_limits, abs_limits)

    def create(self, req, body):
        """Create a new limit."""
        raise webob.exc.HTTPNotImplemented()

    def delete(self, req, id):
        """Delete the limit."""
        raise webob.exc.HTTPNotImplemented()

    def show(self, req, id):
        """Show limit information."""
        raise webob.exc.HTTPNotImplemented()

    def update(self, req, id, body):
        """Update existing limit."""
        raise webob.exc.HTTPNotImplemented()

    def _get_view_builder(self, req):
        return limits_views.ViewBuilder()


def create_resource():
    return wsgi.Resource(LimitsController())


class Limit(object):
    """Stores information about a limit for HTTP requests."""

    UNITS = {v: k for k, v in utils.TIME_UNITS.items()}

    def __init__(self, verb, uri, regex, value, unit):
        """Initialize a new `Limit`.

        @param verb: HTTP verb (POST, PUT, etc.)
        @param uri: Human-readable URI
        @param regex: Regular expression format for this limit
        @param value: Integer number of requests which can be made
        @param unit: Unit of measure for the value parameter
        """
        self.verb = verb
        self.uri = uri
        self.regex = regex
        self.value = int(value)
        self.unit = unit
        self.unit_string = self.display_unit().lower()
        self.remaining = int(value)

        if value <= 0:
            raise ValueError("Limit value must be > 0")

        self.last_request = None
        self.next_request = None

        self.water_level = 0
        self.capacity = self.unit
        self.request_value = float(self.capacity) / float(self.value)
        msg = (_("Only %(value)s %(verb)s request(s) can be "
                 "made to %(uri)s every %(unit_string)s.") %
               {'value': self.value, 'verb': self.verb, 'uri': self.uri,
                'unit_string': self.unit_string})
        self.error_message = msg

    def __call__(self, verb, url):
        """Represents a call to this limit from a relevant request.

        @param verb: string http verb (POST, GET, etc.)
        @param url: string URL
        """
        if self.verb != verb or not re.match(self.regex, url):
            return

        now = self._get_time()

        if self.last_request is None:
            self.last_request = now

        leak_value = now - self.last_request

        self.water_level -= leak_value
        self.water_level = max(self.water_level, 0)
        self.water_level += self.request_value

        difference = self.water_level - self.capacity

        self.last_request = now

        if difference > 0:
            self.water_level -= self.request_value
            self.next_request = now + difference
            return difference

        cap = self.capacity
        water = self.water_level
        val = self.value

        self.remaining = math.floor(((cap - water) / cap) * val)
        self.next_request = now

    def _get_time(self):
        """Retrieve the current time. Broken out for testability."""
        return time.time()

    def display_unit(self):
        """Display the string name of the unit."""
        return self.UNITS.get(self.unit, "UNKNOWN")

    def display(self):
        """Return a useful representation of this class."""
        return {
            "verb": self.verb,
            "URI": self.uri,
            "regex": self.regex,
            "value": self.value,
            "remaining": int(self.remaining),
            "unit": self.display_unit(),
            "resetTime": int(self.next_request or self._get_time()),
        }

# "Limit" format is a dictionary with the HTTP verb, human-readable URI,
# a regular-expression to match, value and unit of measure (PER_DAY, etc.)

DEFAULT_LIMITS = [
    Limit("POST", "*", ".*", 120, utils.TIME_UNITS['MINUTE']),
    Limit("POST", "*/servers", "^/servers", 120, utils.TIME_UNITS['MINUTE']),
    Limit("PUT", "*", ".*", 120, utils.TIME_UNITS['MINUTE']),
    Limit("GET", "*changes-since*", ".*changes-since.*", 120,
          utils.TIME_UNITS['MINUTE']),
    Limit("DELETE", "*", ".*", 120, utils.TIME_UNITS['MINUTE']),
    Limit("GET", "*/os-fping", "^/os-fping", 12, utils.TIME_UNITS['MINUTE']),
]


class RateLimitingMiddleware(base_wsgi.Middleware):
    """Rate-limits requests passing through this middleware. All limit
    information is stored in memory for this implementation.
    """

    def __init__(self, application, limits=None, limiter=None, **kwargs):
        """Initialize new `RateLimitingMiddleware`.

        It wraps the given WSGI application and sets up the given limits.

        @param application: WSGI application to wrap
        @param limits: String describing limits
        @param limiter: String identifying class for representing limits

        Other parameters are passed to the constructor for the limiter.
        """
        base_wsgi.Middleware.__init__(self, application)

        # Select the limiter class
        if limiter is None:
            limiter = Limiter
        else:
            limiter = importutils.import_class(limiter)

        # Parse the limits, if any are provided
        if limits is not None:
            limits = limiter.parse_limits(limits)

        self._limiter = limiter(limits or DEFAULT_LIMITS, **kwargs)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Represents a single call through this middleware.

        We should record the request if we have a limit relevant to it.
        If no limit is relevant to the request, ignore it.

        If the request should be rate limited, return a fault telling the user
        they are over the limit and need to retry later.
        """
        verb = req.method
        url = req.url
        context = req.environ.get("nova.context")

        if context:
            username = context.user_id
        else:
            username = None

        delay, error = self._limiter.check_for_delay(verb, url, username)

        if delay:
            msg = _("This request was rate-limited.")
            retry = time.time() + delay
            return wsgi.RateLimitFault(msg, error, retry)

        req.environ["nova.limits"] = self._limiter.get_limits(username)

        return self.application


class Limiter(object):
    """Rate-limit checking class which handles limits in memory."""

    def __init__(self, limits, **kwargs):
        """Initialize the new `Limiter`.

        @param limits: List of `Limit` objects
        """
        self.limits = copy.deepcopy(limits)
        self.levels = collections.defaultdict(lambda: copy.deepcopy(limits))

        # Pick up any per-user limit information
        for key, value in kwargs.items():
            if key.startswith(LIMITS_PREFIX):
                username = key[len(LIMITS_PREFIX):]
                self.levels[username] = self.parse_limits(value)

    def get_limits(self, username=None):
        """Return the limits for a given user."""
        return [limit.display() for limit in self.levels[username]]

    def check_for_delay(self, verb, url, username=None):
        """Check the given verb/user/user triplet for limit.

        @return: Tuple of delay (in seconds) and error message (or None, None)
        """
        delays = []

        for limit in self.levels[username]:
            delay = limit(verb, url)
            if delay:
                delays.append((delay, limit.error_message))

        if delays:
            delays.sort()
            return delays[0]

        return None, None

    # Note: This method gets called before the class is instantiated,
    # so this must be either a static method or a class method.  It is
    # used to develop a list of limits to feed to the constructor.  We
    # put this in the class so that subclasses can override the
    # default limit parsing.
    @staticmethod
    def parse_limits(limits):
        """Convert a string into a list of Limit instances.  This
        implementation expects a semicolon-separated sequence of
        parenthesized groups, where each group contains a
        comma-separated sequence consisting of HTTP method,
        user-readable URI, a URI reg-exp, an integer number of
        requests which can be made, and a unit of measure.  Valid
        values for the latter are "SECOND", "MINUTE", "HOUR", and
        "DAY".

        @return: List of Limit instances.
        """

        # Handle empty limit strings
        limits = limits.strip()
        if not limits:
            return []

        # Split up the limits by semicolon
        result = []
        for group in limits.split(';'):
            group = group.strip()
            if not group.startswith('(') or not group.endswith(')'):
                raise ValueError("Limit rules must be surrounded by "
                                 "parentheses")
            group = group[1:-1]

            # Extract the Limit arguments
            args = [a.strip() for a in group.split(',')]
            if len(args) != 5:
                raise ValueError("Limit rules must contain the following "
                                 "arguments: verb, uri, regex, value, unit")

            # Pull out the arguments
            verb, uri, regex, value, unit = args

            # Upper-case the verb
            verb = verb.upper()

            # Convert value--raises ValueError if it's not integer
            value = int(value)

            # Convert unit
            unit = unit.upper()
            if unit not in utils.TIME_UNITS:
                raise ValueError("Invalid units specified")
            unit = utils.TIME_UNITS[unit]

            # Build a limit
            result.append(Limit(verb, uri, regex, value, unit))

        return result


class WsgiLimiter(object):
    """Rate-limit checking from a WSGI application. Uses an in-memory
    `Limiter`.

    To use, POST ``/<username>`` with JSON data such as::

        {
            "verb" : GET,
            "path" : "/servers"
        }

    and receive a 204 No Content, or a 403 Forbidden with an X-Wait-Seconds
    header containing the number of seconds to wait before the action would
    succeed.
    """

    def __init__(self, limits=None):
        """Initialize the new `WsgiLimiter`.

        @param limits: List of `Limit` objects
        """
        self._limiter = Limiter(limits or DEFAULT_LIMITS)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, request):
        """Handles a call to this application.

        Returns 204 if the request is acceptable to the limiter, else a 403
        is returned with a relevant header indicating when the request *will*
        succeed.
        """
        if request.method != "POST":
            raise webob.exc.HTTPMethodNotAllowed()

        try:
            info = dict(jsonutils.loads(request.body))
        except ValueError:
            raise webob.exc.HTTPBadRequest()

        username = request.path_info_pop()
        verb = info.get("verb")
        path = info.get("path")

        delay, error = self._limiter.check_for_delay(verb, path, username)

        if delay:
            headers = {"X-Wait-Seconds": "%.2f" % delay}
            return webob.exc.HTTPForbidden(headers=headers, explanation=error)
        else:
            return webob.exc.HTTPNoContent()


class WsgiLimiterProxy(object):
    """Rate-limit requests based on answers from a remote source."""

    def __init__(self, limiter_address):
        """Initialize the new `WsgiLimiterProxy`.

        @param limiter_address: IP/port combination of where to request limit
        """
        self.limiter_address = limiter_address

    def check_for_delay(self, verb, path, username=None):
        body = jsonutils.dumps({"verb": verb, "path": path})
        headers = {"Content-Type": "application/json"}

        conn = httplib.HTTPConnection(self.limiter_address)

        if username:
            conn.request("POST", "/%s" % (username), body, headers)
        else:
            conn.request("POST", "/", body, headers)

        resp = conn.getresponse()

        if 200 >= resp.status < 300:
            return None, None

        return resp.getheader("X-Wait-Seconds"), resp.read() or None

    # Note: This method gets called before the class is instantiated,
    # so this must be either a static method or a class method.  It is
    # used to develop a list of limits to feed to the constructor.
    # This implementation returns an empty list, since all limit
    # decisions are made by a remote server.
    @staticmethod
    def parse_limits(limits):
        """Ignore a limits string--simply doesn't apply for the limit
        proxy.

        @return: Empty list.
        """

        return []
