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
from xml.dom import minidom

import nova.context
from nova.api.openstack import limits
from nova.api.openstack import views
from nova import test


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
        self.absolute_limits = {}

        def stub_get_project_quotas(context, project_id):
            return self.absolute_limits

        self.stubs.Set(nova.quota, "get_project_quotas",
                       stub_get_project_quotas)

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
        self.controller = limits.create_resource('1.0')

    def _get_index_request(self, accept_header="application/json"):
        """Helper to set routing arguments."""
        request = webob.Request.blank("/")
        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        context = nova.context.RequestContext('testuser', 'testproject')
        request.environ["nova.context"] = context
        return request

    def _populate_limits(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("POST", "*", ".*", 5, 60 * 60).display(),
        ]
        request.environ["nova.limits"] = _limits
        return request

    def _setup_absolute_limits(self):
        self.absolute_limits = {
            'instances': 5,
            'cores': 8,
            'ram': 2 ** 13,
            'volumes': 21,
            'gigabytes': 34,
            'metadata_items': 55,
            'injected_files': 89,
            'injected_file_content_bytes': 144,
        }

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
        self._setup_absolute_limits()
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
                "absolute": {
                    "maxTotalInstances": 5,
                    "maxTotalCores": 8,
                    "maxTotalRAMSize": 2 ** 13,
                    "maxServerMeta": 55,
                    "maxImageMeta": 55,
                    "maxPersonality": 89,
                    "maxPersonalitySize": 144,
                },
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def test_empty_index_xml(self):
        """Test getting limit details in XML."""
        request = self._get_index_request("application/xml")
        response = request.get_response(self.controller)

        expected = minidom.parseString("""
            <limits
                xmlns="http://docs.rackspacecloud.com/servers/api/v1.0">
                <rate/>
                <absolute/>
            </limits>
        """.replace("  ", ""))

        body = minidom.parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), body.toxml())

    def test_index_xml(self):
        """Test getting limit details in XML."""
        request = self._get_index_request("application/xml")
        request = self._populate_limits(request)
        response = request.get_response(self.controller)

        expected = minidom.parseString("""
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
        body = minidom.parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), body.toxml())


class LimitsControllerV11Test(BaseLimitTestSuite):
    """
    Tests for `limits.LimitsControllerV11` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        self.controller = limits.create_resource('1.1')
        self.maxDiff = None

    def _get_index_request(self, accept_header="application/json"):
        """Helper to set routing arguments."""
        request = webob.Request.blank("/")
        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        context = nova.context.RequestContext('testuser', 'testproject')
        request.environ["nova.context"] = context
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
        self.absolute_limits = {
            'ram': 512,
            'instances': 5,
            'cores': 21,
        }
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
                                "next-available": "1970-01-01T00:00:00Z",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                            {
                                "verb": "POST",
                                "next-available": "1970-01-01T00:00:00Z",
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
                                "next-available": "1970-01-01T00:00:00Z",
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
                    "maxTotalCores": 21,
                    },
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def _populate_limits_diff_regex(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("GET", "*", "*.*", 10, 60).display(),
        ]
        request.environ["nova.limits"] = _limits
        return request

    def test_index_diff_regex(self):
        """Test getting limit details in JSON."""
        request = self._get_index_request()
        request = self._populate_limits_diff_regex(request)
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
                                "next-available": "1970-01-01T00:00:00Z",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                        ],
                    },
                    {
                        "regex": "*.*",
                        "uri": "*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": "1970-01-01T00:00:00Z",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                        ],
                    },

                ],
                "absolute": {},
            },
        }
        body = json.loads(response.body)
        self.assertEqual(expected, body)

    def _test_index_absolute_limits_json(self, expected):
        request = self._get_index_request()
        response = request.get_response(self.controller)
        body = json.loads(response.body)
        self.assertEqual(expected, body['limits']['absolute'])

    def test_index_ignores_extra_absolute_limits_json(self):
        self.absolute_limits = {'unknown_limit': 9001}
        self._test_index_absolute_limits_json({})

    def test_index_absolute_ram_json(self):
        self.absolute_limits = {'ram': 1024}
        self._test_index_absolute_limits_json({'maxTotalRAMSize': 1024})

    def test_index_absolute_cores_json(self):
        self.absolute_limits = {'cores': 17}
        self._test_index_absolute_limits_json({'maxTotalCores': 17})

    def test_index_absolute_instances_json(self):
        self.absolute_limits = {'instances': 19}
        self._test_index_absolute_limits_json({'maxTotalInstances': 19})

    def test_index_absolute_metadata_json(self):
        # NOTE: both server metadata and image metadata are overloaded
        # into metadata_items
        self.absolute_limits = {'metadata_items': 23}
        expected = {
            'maxServerMeta': 23,
            'maxImageMeta': 23,
        }
        self._test_index_absolute_limits_json(expected)

    def test_index_absolute_injected_files(self):
        self.absolute_limits = {
            'injected_files': 17,
            'injected_file_content_bytes': 86753,
        }
        expected = {
            'maxPersonality': 17,
            'maxPersonalitySize': 86753,
        }
        self._test_index_absolute_limits_json(expected)


class TestLimiter(limits.Limiter):
    pass


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
        _limits = '(GET, *, .*, 1, MINUTE)'
        self.app = limits.RateLimitingMiddleware(self._empty_app, _limits,
                                                 "%s.TestLimiter" %
                                                 self.__class__.__module__)

    def test_limit_class(self):
        """Test that middleware selected correct limiter class."""
        assert isinstance(self.app._limiter, TestLimiter)

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

        root = minidom.parseString(response.body).childNodes[0]
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


class ParseLimitsTest(BaseLimitTestSuite):
    """
    Tests for the default limits parser in the in-memory
    `limits.Limiter` class.
    """

    def test_invalid(self):
        """Test that parse_limits() handles invalid input correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          ';;;;;')

    def test_bad_rule(self):
        """Test that parse_limits() handles bad rules correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          'GET, *, .*, 20, minute')

    def test_missing_arg(self):
        """Test that parse_limits() handles missing args correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, 20)')

    def test_bad_value(self):
        """Test that parse_limits() handles bad values correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, foo, minute)')

    def test_bad_unit(self):
        """Test that parse_limits() handles bad units correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, 20, lightyears)')

    def test_multiple_rules(self):
        """Test that parse_limits() handles multiple rules correctly."""
        try:
            l = limits.Limiter.parse_limits('(get, *, .*, 20, minute);'
                                            '(PUT, /foo*, /foo.*, 10, hour);'
                                            '(POST, /bar*, /bar.*, 5, second);'
                                            '(Say, /derp*, /derp.*, 1, day)')
        except ValueError, e:
            assert False, str(e)

        # Make sure the number of returned limits are correct
        self.assertEqual(len(l), 4)

        # Check all the verbs...
        expected = ['GET', 'PUT', 'POST', 'SAY']
        self.assertEqual([t.verb for t in l], expected)

        # ...the URIs...
        expected = ['*', '/foo*', '/bar*', '/derp*']
        self.assertEqual([t.uri for t in l], expected)

        # ...the regexes...
        expected = ['.*', '/foo.*', '/bar.*', '/derp.*']
        self.assertEqual([t.regex for t in l], expected)

        # ...the values...
        expected = [20, 10, 5, 1]
        self.assertEqual([t.value for t in l], expected)

        # ...and the units...
        expected = [limits.PER_MINUTE, limits.PER_HOUR,
                    limits.PER_SECOND, limits.PER_DAY]
        self.assertEqual([t.unit for t in l], expected)


class LimiterTest(BaseLimitTestSuite):
    """
    Tests for the in-memory `limits.Limiter` class.
    """

    def setUp(self):
        """Run before each test."""
        BaseLimitTestSuite.setUp(self)
        userlimits = {'user:user3': ''}
        self.limiter = limits.Limiter(TEST_LIMITS, **userlimits)

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

    def test_user_limit(self):
        """
        Test user-specific limits.
        """
        self.assertEqual(self.limiter.levels['user3'], [])

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

        # User3
        expected = [None] * 20
        results = list(self._check(20, "PUT", "/anything", "user3"))
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
            request = webob.Request.blank("/", method=method)
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

    def request(self, method, path, body="", headers=None):
        """
        Requests made via this connection actually get translated and routed
        into our WSGI app, we then wait for the response and turn it back into
        an `httplib.HTTPResponse`.
        """
        if not headers:
            headers = {}

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


class LimitsViewBuilderV11Test(test.TestCase):

    def setUp(self):
        self.view_builder = views.limits.ViewBuilderV11()
        self.rate_limits = [{"URI": "*",
                             "regex": ".*",
                             "value": 10,
                             "verb": "POST",
                             "remaining": 2,
                             "unit": "MINUTE",
                             "resetTime": 1311272226},
                            {"URI": "*/servers",
                             "regex": "^/servers",
                             "value": 50,
                             "verb": "POST",
                             "remaining": 10,
                             "unit": "DAY",
                             "resetTime": 1311272226}]
        self.absolute_limits = {"metadata_items": 1,
                                "injected_files": 5,
                                "injected_file_content_bytes": 5}

    def tearDown(self):
        pass

    def test_build_limits(self):
        expected_limits = {"limits": {
                "rate": [{
                      "uri": "*",
                      "regex": ".*",
                      "limit": [{"value": 10,
                                 "verb": "POST",
                                 "remaining": 2,
                                 "unit": "MINUTE",
                                 "next-available": "2011-07-21T18:17:06Z"}]},
                   {"uri": "*/servers",
                    "regex": "^/servers",
                    "limit": [{"value": 50,
                               "verb": "POST",
                               "remaining": 10,
                               "unit": "DAY",
                               "next-available": "2011-07-21T18:17:06Z"}]}],
                "absolute": {"maxServerMeta": 1,
                             "maxImageMeta": 1,
                             "maxPersonality": 5,
                             "maxPersonalitySize": 5}}}

        output = self.view_builder.build(self.rate_limits,
                                         self.absolute_limits)
        self.assertDictMatch(output, expected_limits)

    def test_build_limits_empty_limits(self):
        expected_limits = {"limits": {"rate": [],
                           "absolute": {}}}

        abs_limits = {}
        rate_limits = []
        output = self.view_builder.build(rate_limits, abs_limits)
        self.assertDictMatch(output, expected_limits)


class LimitsXMLSerializationTest(test.TestCase):

    def setUp(self):
        self.maxDiff = None

    def tearDown(self):
        pass

    def test_index(self):
        serializer = limits.LimitsXMLSerializer()
        fixture = {"limits": {
                   "rate": [{
                         "uri": "*",
                         "regex": ".*",
                         "limit": [{
                              "value": 10,
                              "verb": "POST",
                              "remaining": 2,
                              "unit": "MINUTE",
                              "next-available": "2011-12-15T22:42:45Z"}]},
                          {"uri": "*/servers",
                           "regex": "^/servers",
                           "limit": [{
                              "value": 50,
                              "verb": "POST",
                              "remaining": 10,
                              "unit": "DAY",
                              "next-available": "2011-12-15T22:42:45Z"}]}],
                    "absolute": {"maxServerMeta": 1,
                                 "maxImageMeta": 1,
                                 "maxPersonality": 5,
                                 "maxPersonalitySize": 10240}}}

        output = serializer.serialize(fixture, 'index')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <limits xmlns="http://docs.openstack.org/compute/api/v1.1">
            <rates>
                <rate uri="*" regex=".*">
                    <limit value="10" verb="POST" remaining="2"
                        unit="MINUTE"
                        next-available="2011-12-15T22:42:45Z"/>
                </rate>
                <rate uri="*/servers" regex="^/servers">
                    <limit value="50" verb="POST" remaining="10"
                        unit="DAY"
                        next-available="2011-12-15T22:42:45Z"/>
                </rate>
            </rates>
            <absolute>
                <limit name="maxServerMeta" value="1"/>
                <limit name="maxPersonality" value="5"/>
                <limit name="maxImageMeta" value="1"/>
                <limit name="maxPersonalitySize" value="10240"/>
            </absolute>
        </limits>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_index_no_limits(self):
        serializer = limits.LimitsXMLSerializer()

        fixture = {"limits": {
                   "rate": [],
                   "absolute": {}}}

        output = serializer.serialize(fixture, 'index')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <limits xmlns="http://docs.openstack.org/compute/api/v1.1">
            <rates />
            <absolute />
        </limits>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())
