# Copyright 2011 OpenStack LLC.
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
#    under the License.import datetime

"""
Module dedicated functions/classes dealing with rate limiting requests.
"""

import copy
import httplib
import json
import math
import re
import time
import urllib
import webob.exc

from collections import defaultdict

from webob.dec import wsgify

from nova import wsgi
from nova.api.openstack import faults
from nova.api.openstack.views import limits as limits_views
from nova.wsgi import Controller
from nova.wsgi import Middleware


# Convenience constants for the limits dictionary passed to Limiter().
PER_SECOND = 1
PER_MINUTE = 60
PER_HOUR = 60 * 60
PER_DAY = 60 * 60 * 24


class LimitsController(Controller):
    """
    Controller for accessing limits in the OpenStack API.
    """

    _serialization_metadata = {
        "application/xml": {
            "attributes": {
                "limit": ["verb", "URI", "uri", "regex", "value", "unit",
                    "resetTime", "next-available", "remaining", "name"],
            },
            "plurals": {
                "rate": "limit",
            },
        },
    }

    def index(self, req):
        """
        Return all global and rate limit information.
        """
        abs_limits = {}
        rate_limits = req.environ.get("nova.limits", [])

        builder = self._get_view_builder(req)
        return builder.build(rate_limits, abs_limits)

    def _get_view_builder(self, req):
        raise NotImplementedError()


class LimitsControllerV10(LimitsController):
    def _get_view_builder(self, req):
        return limits_views.ViewBuilderV10()


class LimitsControllerV11(LimitsController):
    def _get_view_builder(self, req):
        return limits_views.ViewBuilderV11()


class Limit(object):
    """
    Stores information about a limit for HTTP requets.
    """

    UNITS = {
        1: "SECOND",
        60: "MINUTE",
        60 * 60: "HOUR",
        60 * 60 * 24: "DAY",
    }

    def __init__(self, verb, uri, regex, value, unit):
        """
        Initialize a new `Limit`.

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
        self.error_message = _("Only %(value)s %(verb)s request(s) can be "\
            "made to %(uri)s every %(unit_string)s." % self.__dict__)

    def __call__(self, verb, url):
        """
        Represents a call to this limit from a relevant request.

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
    Limit("POST", "*", ".*", 10, PER_MINUTE),
    Limit("POST", "*/servers", "^/servers", 50, PER_DAY),
    Limit("PUT", "*", ".*", 10, PER_MINUTE),
    Limit("GET", "*changes-since*", ".*changes-since.*", 3, PER_MINUTE),
    Limit("DELETE", "*", ".*", 100, PER_MINUTE),
]


class RateLimitingMiddleware(Middleware):
    """
    Rate-limits requests passing through this middleware. All limit information
    is stored in memory for this implementation.
    """

    def __init__(self, application, limits=None):
        """
        Initialize new `RateLimitingMiddleware`, which wraps the given WSGI
        application and sets up the given limits.

        @param application: WSGI application to wrap
        @param limits: List of dictionaries describing limits
        """
        Middleware.__init__(self, application)
        self._limiter = Limiter(limits or DEFAULT_LIMITS)

    @wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """
        Represents a single call through this middleware. We should record the
        request if we have a limit relevant to it. If no limit is relevant to
        the request, ignore it.

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
            return faults.OverLimitFault(msg, error, retry)

        req.environ["nova.limits"] = self._limiter.get_limits(username)

        return self.application


class Limiter(object):
    """
    Rate-limit checking class which handles limits in memory.
    """

    def __init__(self, limits):
        """
        Initialize the new `Limiter`.

        @param limits: List of `Limit` objects
        """
        self.limits = copy.deepcopy(limits)
        self.levels = defaultdict(lambda: copy.deepcopy(limits))

    def get_limits(self, username=None):
        """
        Return the limits for a given user.
        """
        return [limit.display() for limit in self.levels[username]]

    def check_for_delay(self, verb, url, username=None):
        """
        Check the given verb/user/user triplet for limit.

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


class WsgiLimiter(object):
    """
    Rate-limit checking from a WSGI application. Uses an in-memory `Limiter`.

    To use:
        POST /<username> with JSON data such as:
        {
            "verb" : GET,
            "path" : "/servers"
        }

    and receive a 204 No Content, or a 403 Forbidden with an X-Wait-Seconds
    header containing the number of seconds to wait before the action would
    succeed.
    """

    def __init__(self, limits=None):
        """
        Initialize the new `WsgiLimiter`.

        @param limits: List of `Limit` objects
        """
        self._limiter = Limiter(limits or DEFAULT_LIMITS)

    @wsgify(RequestClass=wsgi.Request)
    def __call__(self, request):
        """
        Handles a call to this application. Returns 204 if the request is
        acceptable to the limiter, else a 403 is returned with a relevant
        header indicating when the request *will* succeed.
        """
        if request.method != "POST":
            raise webob.exc.HTTPMethodNotAllowed()

        try:
            info = dict(json.loads(request.body))
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
    """
    Rate-limit requests based on answers from a remote source.
    """

    def __init__(self, limiter_address):
        """
        Initialize the new `WsgiLimiterProxy`.

        @param limiter_address: IP/port combination of where to request limit
        """
        self.limiter_address = limiter_address

    def check_for_delay(self, verb, path, username=None):
        body = json.dumps({"verb": verb, "path": path})
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
