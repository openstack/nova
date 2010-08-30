# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Test WSGI basics and provide some helper functions for other WSGI tests.
"""

import unittest

import routes
import webob

from nova import wsgi


class Test(unittest.TestCase):

    def test_debug(self):

        class Application(wsgi.Application):
            """Dummy application to test debug."""

            def __call__(self, environ, start_response):
                start_response("200", [("X-Test", "checking")])
                return ['Test result']

        application = wsgi.Debug(Application())
        result = webob.Request.blank('/').get_response(application)
        self.assertEqual(result.body, "Test result")

    def test_router(self):

        class Application(wsgi.Application):
            """Test application to call from router."""

            def __call__(self, environ, start_response):
                start_response("200", [])
                return ['Router result']

        class Router(wsgi.Router):
            """Test router."""

            def __init__(self):
                mapper = routes.Mapper()
                mapper.connect("/test", controller=Application())
                super(Router, self).__init__(mapper)

        result = webob.Request.blank('/test').get_response(Router())
        self.assertEqual(result.body, "Router result")
        result = webob.Request.blank('/bad').get_response(Router())
        self.assertNotEqual(result.body, "Router result")

    def test_controller(self):

        class Controller(wsgi.Controller):
            """Test controller to call from router."""
            test = self

            def show(self, req, id): # pylint: disable-msg=W0622,C0103
                """Default action called for requests with an ID."""
                self.test.assertEqual(req.path_info, '/tests/123')
                self.test.assertEqual(id, '123')
                return id

        class Router(wsgi.Router):
            """Test router."""

            def __init__(self):
                mapper = routes.Mapper()
                mapper.resource("test", "tests", controller=Controller())
                super(Router, self).__init__(mapper)

        result = webob.Request.blank('/tests/123').get_response(Router())
        self.assertEqual(result.body, "123")
        result = webob.Request.blank('/test/123').get_response(Router())
        self.assertNotEqual(result.body, "123")

    def test_serializer(self):
        # TODO(eday): Placeholder for serializer testing.
        pass
