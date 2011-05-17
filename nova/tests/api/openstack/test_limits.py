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
#    under the License.

"""
Tests dealing with HTTP rate-limiting.
"""

import httplib
import json
import StringIO
import stubout
import time
import unittest
import webob

from xml.dom.minidom import parseString

from nova.api.openstack import limits


TEST_LIMITS = [
    limits.Limit("GET", "/delayed", "^/delayed", 1, limits.PER_MINUTE),
    limits.Limit("POST", "*", ".*", 7, limits.PER_MINUTE),
    limits.Limit("POST", "/servers", "^/servers", 3, limits.PER_MINUTE),
    limits.Limit("PUT", "*", "", 10, limits.PER_MINUTE),
    limits.Limit("PUT", "/servers", "^/servers", 5, limits.PER_MINUTE),
]


class BaseLimitTestSuite(unittest.TestCase):
    """Base test suite which provides relevant stubs and time abstraction."""

    def setUp(self):
        """Run before each test."""
        self.time = 0.0
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(limits.Limit, "_get_time", self._get_time)

    def tearDown(self):
        """Run after each test."""
        self.stubs.UnsetAll()

    def _get_time(self):
        """Return the "time" according to this test suite."""
        return self.time


class LimitsControllerV10Test(BaseLimitTestSuite):
    """
    Tests for `limits.LimitsControllerV10` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        self.controller = limits.LimitsControllerV10()

    def _get_index_request(self, accept_header="application/json"):
        """Helper to set routing arguments."""
        request = webob.Request.blank("/")
        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        return request

    def _populate_limits(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("POST", "*", ".*", 5, 60 * 60).display(),
        ]
        request.environ["nova.limits"] = _limits
        return request

    def test_empty_index_json(self):
        """Test getting empty limit details in JSON."""
        request = self._get_index_request()
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def test_index_json(self):
        """Test getting limit details in JSON."""
        request = self._get_index_request()
        request = self._populate_limits(request)
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [{
                    "regex": ".*",
                    "resetTime": 0,
                    "URI": "*",
                    "value": 10,
                    "verb": "GET",
                    "remaining": 10,
                    "unit": "MINUTE",
                },
                {
                    "regex": ".*",
                    "resetTime": 0,
                    "URI": "*",
                    "value": 5,
                    "verb": "POST",
                    "remaining": 5,
                    "unit": "HOUR",
                }],
                "absolute": {},
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def test_empty_index_xml(self):
        """Test getting limit details in XML."""
        request = self._get_index_request("application/xml")
        response = request.get_response(self.controller)

        expected = parseString("""
            <limits
                xmlns="http://docs.rackspacecloud.com/servers/api/v1.0">
                <rate/>
                <absolute/>
            </limits>
        """.replace("  ", ""))

        body = parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), body.toxml())

    def test_index_xml(self):
        """Test getting limit details in XML."""
        request = self._get_index_request("application/xml")
        request = self._populate_limits(request)
        response = request.get_response(self.controller)

        expected = parseString("""
            <limits
                xmlns="http://docs.rackspacecloud.com/servers/api/v1.0">
                <rate>
                    <limit URI="*" regex=".*" remaining="10" resetTime="0"
                        unit="MINUTE" value="10" verb="GET"/>
                    <limit URI="*" regex=".*" remaining="5" resetTime="0"
                        unit="HOUR" value="5" verb="POST"/>
                </rate>
                <absolute/>
            </limits>
        """.replace("  ", ""))
        body = parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), body.toxml())


class LimitsControllerV11Test(BaseLimitTestSuite):
    """
    Tests for `limits.LimitsControllerV11` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        self.controller = limits.LimitsControllerV11()

    def _get_index_request(self, accept_header="application/json"):
        """Helper to set routing arguments."""
        request = webob.Request.blank("/")
        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        return request

    def _populate_limits(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("POST", "*", ".*", 5, 60 * 60).display(),
            limits.Limit("GET", "changes-since*", "changes-since",
                         5, 60).display(),
        ]
        request.environ["nova.limits"] = _limits
        #set absolute limits here
        limits.TEST_ABSOLUTE_LIMITS = {"ram": 512, "instances": 5}

        return request

    def test_empty_index_json(self):
        """Test getting empty limit details in JSON."""
        request = self._get_index_request()
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def test_index_json(self):
        """Test getting limit details in JSON."""
        request = self._get_index_request()
        request = self._populate_limits(request)
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [
                    {
                        "regex": ".*",
                        "uri": "*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": 0,
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                            {
                                "verb": "POST",
                                "next-available": 0,
                                "unit": "HOUR",
                                "value": 5,
                                "remaining": 5,
                            },
                        ],
                    },
                    {
                        "regex": "changes-since",
                        "uri": "changes-since*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": 0,
                                "unit": "MINUTE",
                                "value": 5,
                                "remaining": 5,
                            },
                        ],
                    },

                ],
                "absolute": {
                    "maxTotalRAMSize": 512,
                    "maxTotalInstances": 5,
                    },
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)


class LimitMiddlewareTest(BaseLimitTestSuite):
    """
    Tests for the `limits.RateLimitingMiddleware` class.
    """

    @webob.dec.wsgify
    def _empty_app(self, request):
        """Do-nothing WSGI app."""
        pass

    def setUp(self):
        """Prepare middleware for use through fake WSGI app."""
        BaseLimitTestSuite.setUp(self)
        _limits = [
            limits.Limit("GET", "*", ".*", 1, 60),
        ]
        self.app = limits.RateLimitingMiddleware(self._empty_app, _limits)

    def test_good_request(self):
        """Test successful GET request through middleware."""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_limited_request_json(self):
        """Test a rate-limited (403) GET request through middleware."""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 403)

        body = json.loads(response.body)
        expected = "Only 1 GET request(s) can be made to * every minute."
        value = body["overLimitFault"]["details"].strip()
        self.assertEqual(value, expected)

    def test_limited_request_xml(self):
        """Test a rate-limited (403) response as XML"""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

        request = webob.Request.blank("/")
        request.accept = "application/xml"
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 403)

        root = parseString(response.body).childNodes[0]
        expected = "Only 1 GET request(s) can be made to * every minute."

        details = root.getElementsByTagName("details")
        self.assertEqual(details.length, 1)

        value = details.item(0).firstChild.data.strip()
        self.assertEqual(value, expected)


class LimitTest(BaseLimitTestSuite):
    """
    Tests for the `limits.Limit` class.
    """

    def test_GET_no_delay(self):
        """Test a limit handles 1 GET per second."""
        limit = limits.Limit("GET", "*", ".*", 1, 1)
        delay = limit("GET", "/anything")
        self.assertEqual(None, delay)
        self.assertEqual(0, limit.next_request)
        self.assertEqual(0, limit.last_request)

    def test_GET_delay(self):
        """Test two calls to 1 GET per second limit."""
        limit = limits.Limit("GET", "*", ".*", 1, 1)
        delay = limit("GET", "/anything")
        self.assertEqual(None, delay)

        delay = limit("GET", "/anything")
        self.assertEqual(1, delay)
        self.assertEqual(1, limit.next_request)
        self.assertEqual(0, limit.last_request)

        self.time += 4

        delay = limit("GET", "/anything")
        self.assertEqual(None, delay)
        self.assertEqual(4, limit.next_request)
        self.assertEqual(4, limit.last_request)


class LimiterTest(BaseLimitTestSuite):
    """
    Tests for the in-memory `limits.Limiter` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        self.limiter = limits.Limiter(TEST_LIMITS)

    def _check(self, num, verb, url, username=None):
        """Check and yield results from checks."""
        for x in xrange(num):
            yield self.limiter.check_for_delay(verb, url, username)[0]

    def _check_sum(self, num, verb, url, username=None):
        """Check and sum results from checks."""
        results = self._check(num, verb, url, username)
        return sum(item for item in results if item)

    def test_no_delay_GET(self):
        """
        Simple test to ensure no delay on a single call for a limit verb we
        didn"t set.
        """
        delay = self.limiter.check_for_delay("GET", "/anything")
        self.assertEqual(delay, (None, None))

    def test_no_delay_PUT(self):
        """
        Simple test to ensure no delay on a single call for a known limit.
        """
        delay = self.limiter.check_for_delay("PUT", "/anything")
        self.assertEqual(delay, (None, None))

    def test_delay_PUT(self):
        """
        Ensure the 11th PUT will result in a delay of 6.0 seconds until
        the next request will be granced.
        """
        expected = [None] * 10 + [6.0]
        results = list(self._check(11, "PUT", "/anything"))

        self.assertEqual(expected, results)

    def test_delay_POST(self):
        """
        Ensure the 8th POST will result in a delay of 6.0 seconds until
        the next request will be granced.
        """
        expected = [None] * 7
        results = list(self._check(7, "POST", "/anything"))
        self.assertEqual(expected, results)

        expected = 60.0 / 7.0
        results = self._check_sum(1, "POST", "/anything")
        self.failUnlessAlmostEqual(expected, results, 8)

    def test_delay_GET(self):
        """
        Ensure the 11th GET will result in NO delay.
        """
        expected = [None] * 11
        results = list(self._check(11, "GET", "/anything"))

        self.assertEqual(expected, results)

    def test_delay_PUT_servers(self):
        """
        Ensure PUT on /servers limits at 5 requests, and PUT elsewhere is still
        OK after 5 requests...but then after 11 total requests, PUT limiting
        kicks in.
        """
        # First 6 requests on PUT /servers
        expected = [None] * 5 + [12.0]
        results = list(self._check(6, "PUT", "/servers"))
        self.assertEqual(expected, results)

        # Next 5 request on PUT /anything
        expected = [None] * 4 + [6.0]
        results = list(self._check(5, "PUT", "/anything"))
        self.assertEqual(expected, results)

    def test_delay_PUT_wait(self):
        """
        Ensure after hitting the limit and then waiting for the correct
        amount of time, the limit will be lifted.
        """
        expected = [None] * 10 + [6.0]
        results = list(self._check(11, "PUT", "/anything"))
        self.assertEqual(expected, results)

        # Advance time
        self.time += 6.0

        expected = [None, 6.0]
        results = list(self._check(2, "PUT", "/anything"))
        self.assertEqual(expected, results)

    def test_multiple_delays(self):
        """
        Ensure multiple requests still get a delay.
        """
        expected = [None] * 10 + [6.0] * 10
        results = list(self._check(20, "PUT", "/anything"))
        self.assertEqual(expected, results)

        self.time += 1.0

        expected = [5.0] * 10
        results = list(self._check(10, "PUT", "/anything"))
        self.assertEqual(expected, results)

    def test_multiple_users(self):
        """
        Tests involving multiple users.
        """
        # User1
        expected = [None] * 10 + [6.0] * 10
        results = list(self._check(20, "PUT", "/anything", "user1"))
        self.assertEqual(expected, results)

        # User2
        expected = [None] * 10 + [6.0] * 5
        results = list(self._check(15, "PUT", "/anything", "user2"))
        self.assertEqual(expected, results)

        self.time += 1.0

        # User1 again
        expected = [5.0] * 10
        results = list(self._check(10, "PUT", "/anything", "user1"))
        self.assertEqual(expected, results)

        self.time += 1.0

        # User1 again
        expected = [4.0] * 5
        results = list(self._check(5, "PUT", "/anything", "user2"))
        self.assertEqual(expected, results)


class WsgiLimiterTest(BaseLimitTestSuite):
    """
    Tests for `limits.WsgiLimiter` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        self.app = limits.WsgiLimiter(TEST_LIMITS)

    def _request_data(self, verb, path):
        """Get data decribing a limit request verb/path."""
        return json.dumps({"verb": verb, "path": path})

    def _request(self, verb, url, username=None):
        """Make sure that POSTing to the given url causes the given username
        to perform the given action.  Make the internal rate limiter return
        delay and make sure that the WSGI app returns the correct response.
        """
        if username:
            request = webob.Request.blank("/%s" % username)
        else:
            request = webob.Request.blank("/")

        request.method = "POST"
        request.body = self._request_data(verb, url)
        response = request.get_response(self.app)

        if "X-Wait-Seconds" in response.headers:
            self.assertEqual(response.status_int, 403)
            return response.headers["X-Wait-Seconds"]

        self.assertEqual(response.status_int, 204)

    def test_invalid_methods(self):
        """Only POSTs should work."""
        requests = []
        for method in ["GET", "PUT", "DELETE", "HEAD", "OPTIONS"]:
            request = webob.Request.blank("/")
            request.body = self._request_data("GET", "/something")
            response = request.get_response(self.app)
            self.assertEqual(response.status_int, 405)

    def test_good_url(self):
        delay = self._request("GET", "/something")
        self.assertEqual(delay, None)

    def test_escaping(self):
        delay = self._request("GET", "/something/jump%20up")
        self.assertEqual(delay, None)

    def test_response_to_delays(self):
        delay = self._request("GET", "/delayed")
        self.assertEqual(delay, None)

        delay = self._request("GET", "/delayed")
        self.assertEqual(delay, '60.00')

    def test_response_to_delays_usernames(self):
        delay = self._request("GET", "/delayed", "user1")
        self.assertEqual(delay, None)

        delay = self._request("GET", "/delayed", "user2")
        self.assertEqual(delay, None)

        delay = self._request("GET", "/delayed", "user1")
        self.assertEqual(delay, '60.00')

        delay = self._request("GET", "/delayed", "user2")
        self.assertEqual(delay, '60.00')


class FakeHttplibSocket(object):
    """
    Fake `httplib.HTTPResponse` replacement.
    """

    def __init__(self, response_string):
        """Initialize new `FakeHttplibSocket`."""
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer."""
        return self._buffer


class FakeHttplibConnection(object):
    """
    Fake `httplib.HTTPConnection`.
    """

    def __init__(self, app, host):
        """
        Initialize `FakeHttplibConnection`.
        """
        self.app = app
        self.host = host

    def request(self, method, path, body="", headers={}):
        """
        Requests made via this connection actually get translated and routed
        into our WSGI app, we then wait for the response and turn it back into
        an `httplib.HTTPResponse`.
        """
        req = webob.Request.blank(path)
        req.method = method
        req.headers = headers
        req.host = self.host
        req.body = body

        resp = str(req.get_response(self.app))
        resp = "HTTP/1.0 %s" % resp
        sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(sock)
        self.http_response.begin()

    def getresponse(self):
        """Return our generated response from the request."""
        return self.http_response


def wire_HTTPConnection_to_WSGI(host, app):
    """Monkeypatches HTTPConnection so that if you try to connect to host, you
    are instead routed straight to the given WSGI app.

    After calling this method, when any code calls

    httplib.HTTPConnection(host)

    the connection object will be a fake.  Its requests will be sent directly
    to the given WSGI app rather than through a socket.

    Code connecting to hosts other than host will not be affected.

    This method may be called multiple times to map different hosts to
    different apps.
    """
    class HTTPConnectionDecorator(object):
        """Wraps the real HTTPConnection class so that when you instantiate
        the class you might instead get a fake instance."""

        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __call__(self, connection_host, *args, **kwargs):
            if connection_host == host:
                return FakeHttplibConnection(app, host)
            else:
                return self.wrapped(connection_host, *args, **kwargs)

    httplib.HTTPConnection = HTTPConnectionDecorator(httplib.HTTPConnection)


class WsgiLimiterProxyTest(BaseLimitTestSuite):
    """
    Tests for the `limits.WsgiLimiterProxy` class.
    """

    def setUp(self):
        """
        Do some nifty HTTP/WSGI magic which allows for WSGI to be called
        directly by something like the `httplib` library.
        """
        BaseLimitTestSuite.setUp(self)
        self.app = limits.WsgiLimiter(TEST_LIMITS)
        wire_HTTPConnection_to_WSGI("169.254.0.1:80", self.app)
        self.proxy = limits.WsgiLimiterProxy("169.254.0.1:80")

    def test_200(self):
        """Successful request test."""
        delay = self.proxy.check_for_delay("GET", "/anything")
        self.assertEqual(delay, (None, None))

    def test_403(self):
        """Forbidden request test."""
        delay = self.proxy.check_for_delay("GET", "/delayed")
        self.assertEqual(delay, (None, None))

        delay, error = self.proxy.check_for_delay("GET", "/delayed")
        error = error.strip()

        expected = ("60.00", "403 Forbidden\n\nOnly 1 GET request(s) can be "\
            "made to /delayed every minute.")

        self.assertEqual((delay, error), expected)
