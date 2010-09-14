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

import unittest

from nova.api.rackspace.ratelimiting import RateLimitingMiddleware
from nova.tests.api.test_helper import *
from webob import Request

class RateLimitingMiddlewareTest(unittest.TestCase):
    def setUp(self):
        self.middleware = RateLimitingMiddleware(APIStub())
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_action_name(self):
        middleware = RateLimitingMiddleware(APIStub())
        def verify(method, url, action_name):
            req = Request(url)
            req.method = method
            action = middleware.get_action_name(req)
            self.assertEqual(action, action_name)
        verify('PUT', '/servers/4', 'PUT')
        verify('DELETE', '/servers/4', 'DELETE')
        verify('POST', '/images/4', 'POST')
        verify('POST', '/servers/4', 'POST servers')
        verify('GET', '/foo?a=4&changes-since=never&b=5', 'GET changes-since')
        verify('GET', '/foo?a=4&monkeys-since=never&b=5', None)
        verify('GET', '/servers/4', None)
        verify('HEAD', '/servers/4', None)

    def TODO_test_call(self):
        pass
        #mw = make_middleware()
        #req = build_request('DELETE', '/servers/4')
        #for i in range(5):
        #    resp = req.get_response(mw)
        #    assert resp is OK
        #resp = req.get_response(mw)
        #assert resp is rate limited
