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

# NOTE(vish): this forces the fixtures from tests/__init.py:setup() to work
from nova.tests import *

import webob.dec
from nova import test

from nova import context
from nova.api.openstack.limits import RateLimitingMiddleware
from nova.api.openstack.common import limited
from nova.tests.api.openstack import fakes
from webob import Request


@webob.dec.wsgify
def simple_wsgi(req):
    return ""


class RateLimitingMiddlewareTest(test.TestCase):

    def test_get_action_name(self):
        middleware = RateLimitingMiddleware(simple_wsgi)

        def verify(method, url, action_name):
            req = Request.blank(url)
            req.method = method
            action = middleware.get_action_name(req)
            self.assertEqual(action, action_name)

        verify('PUT', '/fake/servers/4', 'PUT')
        verify('DELETE', '/fake/servers/4', 'DELETE')
        verify('POST', '/fake/images/4', 'POST')
        verify('POST', '/fake/servers/4', 'POST servers')
        verify('GET', '/fake/foo?a=4&changes-since=never&b=5',
               'GET changes-since')
        verify('GET', '/fake/foo?a=4&monkeys-since=never&b=5', None)
        verify('GET', '/fake/servers/4', None)
        verify('HEAD', '/fake/servers/4', None)

    def exhaust(self, middleware, method, url, username, times):
        req = Request.blank(url, dict(REQUEST_METHOD=method),
                            headers={'X-Auth-User': username})
        req.environ['nova.context'] = context.RequestContext(username,
                            username)
        for i in range(times):
            resp = req.get_response(middleware)
            self.assertEqual(resp.status_int, 200)
        resp = req.get_response(middleware)
        self.assertEqual(resp.status_int, 413)
        self.assertTrue('Retry-After' in resp.headers)

    def test_single_action(self):
        middleware = RateLimitingMiddleware(simple_wsgi)
        self.exhaust(middleware, 'DELETE', '/fake/servers/4', 'usr1', 100)
        self.exhaust(middleware, 'DELETE', '/fake/servers/4', 'usr2', 100)

    def test_POST_servers_action_implies_POST_action(self):
        middleware = RateLimitingMiddleware(simple_wsgi)
        self.exhaust(middleware, 'POST', '/fake/servers/4', 'usr1', 10)
        self.exhaust(middleware, 'POST', '/fake/images/4', 'usr2', 10)
        self.assertTrue(set(middleware.limiter._levels) == \
                        set(['usr1:POST', 'usr1:POST servers', 'usr2:POST']))

    def test_POST_servers_action_correctly_ratelimited(self):
        middleware = RateLimitingMiddleware(simple_wsgi)
        # Use up all of our "POST" allowance for the minute, 5 times
        for i in range(5):
            self.exhaust(middleware, 'POST', '/fake/servers/4', 'usr1', 10)
            # Reset the 'POST' action counter.
            del middleware.limiter._levels['usr1:POST']
        # All 50 daily "POST servers" actions should be all used up
        self.exhaust(middleware, 'POST', '/fake/servers/4', 'usr1', 0)

    def test_proxy_ctor_works(self):
        middleware = RateLimitingMiddleware(simple_wsgi)
        self.assertEqual(middleware.limiter.__class__.__name__, "Limiter")
        middleware = RateLimitingMiddleware(simple_wsgi, service_host='foobar')
        self.assertEqual(middleware.limiter.__class__.__name__, "WSGIAppProxy")
