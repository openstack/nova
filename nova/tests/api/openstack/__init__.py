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

from nova.api.openstack import limited
from nova.api.openstack import RateLimitingMiddleware
from nova.tests.api.fakes import APIStub
from webob import Request


class RateLimitingMiddlewareTest(unittest.TestCase):

    def test_get_action_name(self):
        middleware = RateLimitingMiddleware(APIStub())
        def verify(method, url, action_name):
            req = Request.blank(url)
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

    def exhaust(self, middleware, method, url, username, times):
        req = Request.blank(url, dict(REQUEST_METHOD=method),
                            headers={'X-Auth-User': username})
        for i in range(times):
            resp = req.get_response(middleware)
            self.assertEqual(resp.status_int, 200)
        resp = req.get_response(middleware)
        self.assertEqual(resp.status_int, 413)
        self.assertTrue('Retry-After' in resp.headers)

    def test_single_action(self):
        middleware = RateLimitingMiddleware(APIStub())
        self.exhaust(middleware, 'DELETE', '/servers/4', 'usr1', 100)
        self.exhaust(middleware, 'DELETE', '/servers/4', 'usr2', 100)

    def test_POST_servers_action_implies_POST_action(self):
        middleware = RateLimitingMiddleware(APIStub())
        self.exhaust(middleware, 'POST', '/servers/4', 'usr1', 10)
        self.exhaust(middleware, 'POST', '/images/4', 'usr2', 10)
        self.assertTrue(set(middleware.limiter._levels) == 
                        set(['usr1:POST', 'usr1:POST servers', 'usr2:POST']))

    def test_POST_servers_action_correctly_ratelimited(self):
        middleware = RateLimitingMiddleware(APIStub())
        # Use up all of our "POST" allowance for the minute, 5 times
        for i in range(5):
            self.exhaust(middleware, 'POST', '/servers/4', 'usr1', 10)
            # Reset the 'POST' action counter.
            del middleware.limiter._levels['usr1:POST']
        # All 50 daily "POST servers" actions should be all used up
        self.exhaust(middleware, 'POST', '/servers/4', 'usr1', 0)

    def test_proxy_ctor_works(self):
        middleware = RateLimitingMiddleware(APIStub())
        self.assertEqual(middleware.limiter.__class__.__name__, "Limiter")
        middleware = RateLimitingMiddleware(APIStub(), service_host='foobar')
        self.assertEqual(middleware.limiter.__class__.__name__, "WSGIAppProxy")


class LimiterTest(unittest.TestCase):

    def test_limiter(self):
        items = range(2000)
        req = Request.blank('/')
        self.assertEqual(limited(items, req), items[ :1000])
        req = Request.blank('/?offset=0')
        self.assertEqual(limited(items, req), items[ :1000])
        req = Request.blank('/?offset=3')
        self.assertEqual(limited(items, req), items[3:1003])
        req = Request.blank('/?offset=2005')
        self.assertEqual(limited(items, req), [])
        req = Request.blank('/?limit=10')
        self.assertEqual(limited(items, req), items[ :10])
        req = Request.blank('/?limit=0')
        self.assertEqual(limited(items, req), items[ :1000])
        req = Request.blank('/?limit=3000')
        self.assertEqual(limited(items, req), items[ :1000])
        req = Request.blank('/?offset=1&limit=3')
        self.assertEqual(limited(items, req), items[1:4])
        req = Request.blank('/?offset=3&limit=0')
        self.assertEqual(limited(items, req), items[3:1003])
        req = Request.blank('/?offset=3&limit=1500')
        self.assertEqual(limited(items, req), items[3:1003])
        req = Request.blank('/?offset=3000&limit=10')
        self.assertEqual(limited(items, req), [])
