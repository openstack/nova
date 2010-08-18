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

from nova import wsgi


class Test(unittest.TestCase):

    def setUp(self): # pylint: disable-msg=C0103
        self.called = False

    def test_debug(self):

        class Application(wsgi.Application):
            """Dummy application to test debug."""
            test = self

            def __call__(self, environ, test_start_response):
                test_start_response("200", [("X-Test", "checking")])
                self.test.called = True
                return ['Test response']

        app = wsgi.Debug(Application())(get_environ(), start_response)
        self.assertTrue(self.called)
        for _ in app:
            pass

    def test_router(self):

        class Application(wsgi.Application):
            """Test application to call from router."""
            test = self

            def __call__(self, environ, test_start_response):
                test_start_response("200", [])
                self.test.called = True
                return []

        class Router(wsgi.Router):
            """Test router."""

            def __init__(self):
                mapper = routes.Mapper()
                mapper.connect("/test", controller=Application())
                super(Router, self).__init__(mapper)

        Router()(get_environ({'PATH_INFO': '/test'}), start_response)
        self.assertTrue(self.called)
        self.called = False
        Router()(get_environ({'PATH_INFO': '/bad'}), start_response)
        self.assertFalse(self.called)

    def test_controller(self):

        class Controller(wsgi.Controller):
            """Test controller to call from router."""
            test = self

            def show(self, **kwargs):
                """Mark that this has been called."""
                self.test.called = True
                self.test.assertEqual(kwargs['id'], '123')
                return "Test"

        class Router(wsgi.Router):
            """Test router."""

            def __init__(self):
                mapper = routes.Mapper()
                mapper.resource("test", "tests", controller=Controller())
                super(Router, self).__init__(mapper)

        Router()(get_environ({'PATH_INFO': '/tests/123'}), start_response)
        self.assertTrue(self.called)
        self.called = False
        Router()(get_environ({'PATH_INFO': '/test/123'}), start_response)
        self.assertFalse(self.called)

    def test_serializer(self):
        # TODO(eday): Placeholder for serializer testing.
        pass


def get_environ(overwrite={}): # pylint: disable-msg=W0102
    """Get a WSGI environment, overwriting any entries given."""
    environ = {'SERVER_PROTOCOL': 'HTTP/1.1',
               'GATEWAY_INTERFACE': 'CGI/1.1',
               'wsgi.version': (1, 0),
               'SERVER_PORT': '443',
               'SERVER_NAME': '127.0.0.1',
               'REMOTE_ADDR': '127.0.0.1',
               'wsgi.run_once': False,
               'wsgi.errors': None,
               'wsgi.multiprocess': False,
               'SCRIPT_NAME': '',
               'wsgi.url_scheme': 'https',
               'wsgi.input': None,
               'REQUEST_METHOD': 'GET',
               'PATH_INFO': '/',
               'CONTENT_TYPE': 'text/plain',
               'wsgi.multithread': True,
               'QUERY_STRING': '',
               'eventlet.input': None}
    return dict(environ, **overwrite)


def start_response(_status, _headers):
    """Dummy start_response to use with WSGI tests."""
    pass
