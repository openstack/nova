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
"""Unit tests for the functions used by the placement API handlers."""

import microversion_parse
import mock
import routes
import testtools
import webob

from nova.api.openstack.placement import handler
from nova.api.openstack.placement.handlers import root
from nova.api.openstack.placement import microversion
from nova.tests import uuidsentinel


# Used in tests below
def start_response(*args, **kwargs):
    pass


def _environ(path='/moo', method='GET'):
    return {
        'PATH_INFO': path,
        'REQUEST_METHOD': method,
        'SERVER_NAME': 'example.com',
        'SERVER_PORT': '80',
        'wsgi.url_scheme': 'http',
        # The microversion version value is not used, but it
        # needs to be set to avoid a KeyError.
        microversion.MICROVERSION_ENVIRON: microversion_parse.Version(1, 12),
    }


class DispatchTest(testtools.TestCase):

    def setUp(self):
        super(DispatchTest, self).setUp()
        self.mapper = routes.Mapper()
        self.route_handler = mock.MagicMock()

    def test_no_match_null_map(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          handler.dispatch,
                          _environ(), start_response,
                          self.mapper)

    def test_no_match_with_map(self):
        self.mapper.connect('/foobar', action='hello')
        self.assertRaises(webob.exc.HTTPNotFound,
                          handler.dispatch,
                          _environ(), start_response,
                          self.mapper)

    def test_simple_match(self):
        self.mapper.connect('/foobar', action=self.route_handler,
                            conditions=dict(method=['GET']))
        environ = _environ(path='/foobar')
        handler.dispatch(environ, start_response, self.mapper)
        self.route_handler.assert_called_with(environ, start_response)

    def test_simple_match_routing_args(self):
        self.mapper.connect('/foobar/{id}', action=self.route_handler,
                            conditions=dict(method=['GET']))
        environ = _environ(path='/foobar/%s' % uuidsentinel.foobar)
        handler.dispatch(environ, start_response, self.mapper)
        self.route_handler.assert_called_with(environ, start_response)
        self.assertEqual(uuidsentinel.foobar,
                         environ['wsgiorg.routing_args'][1]['id'])


class MapperTest(testtools.TestCase):

    def setUp(self):
        super(MapperTest, self).setUp()
        declarations = {
            '/hello': {'GET': 'hello'}
        }
        self.mapper = handler.make_map(declarations)

    def test_no_match(self):
        environ = _environ(path='/cow')
        self.assertIsNone(self.mapper.match(environ=environ))

    def test_match(self):
        environ = _environ(path='/hello')
        action = self.mapper.match(environ=environ)['action']
        self.assertEqual('hello', action)

    def test_405_methods(self):
        environ = _environ(path='/hello', method='POST')
        result = self.mapper.match(environ=environ)
        self.assertEqual(handler.handle_405, result['action'])
        self.assertEqual('GET', result['_methods'])

    def test_405_headers(self):
        environ = _environ(path='/hello', method='POST')
        global headers, status
        headers = status = None

        def local_start_response(*args, **kwargs):
            global headers, status
            status = args[0]
            headers = {header[0]: header[1] for header in args[1]}

        handler.dispatch(environ, local_start_response, self.mapper)
        allow_header = headers['allow']
        self.assertEqual('405 Method Not Allowed', status)
        self.assertEqual('GET', allow_header)
        # PEP 3333 requires that headers be whatever the native str
        # is in that version of Python. Never unicode.
        self.assertEqual(str, type(allow_header))


class PlacementLoggingTest(testtools.TestCase):

    @mock.patch("nova.api.openstack.placement.handler.LOG")
    def test_404_no_error_log(self, mocked_log):
        environ = _environ(path='/hello', method='GET')
        context_mock = mock.Mock()
        context_mock.to_policy_values.return_value = {'roles': ['admin']}
        environ['placement.context'] = context_mock
        app = handler.PlacementHandler()
        self.assertRaises(webob.exc.HTTPNotFound,
                          app, environ, start_response)
        mocked_log.error.assert_not_called()
        mocked_log.exception.assert_not_called()


class DeclarationsTest(testtools.TestCase):

    def setUp(self):
        super(DeclarationsTest, self).setUp()
        self.mapper = handler.make_map(handler.ROUTE_DECLARATIONS)

    def test_root_slash_match(self):
        environ = _environ(path='/')
        result = self.mapper.match(environ=environ)
        self.assertEqual(root.home, result['action'])

    def test_root_empty_match(self):
        environ = _environ(path='')
        result = self.mapper.match(environ=environ)
        self.assertEqual(root.home, result['action'])


class ContentHeadersTest(testtools.TestCase):

    def setUp(self):
        super(ContentHeadersTest, self).setUp()
        self.environ = _environ(path='/')
        self.app = handler.PlacementHandler()

    def test_no_content_type(self):
        self.environ['CONTENT_LENGTH'] = '10'
        self.assertRaisesRegex(webob.exc.HTTPBadRequest,
                               "content-type header required when "
                               "content-length > 0", self.app,
                               self.environ, start_response)

    def test_non_integer_content_length(self):
        self.environ['CONTENT_LENGTH'] = 'foo'
        self.assertRaisesRegex(webob.exc.HTTPBadRequest,
                               "content-length header must be an integer",
                               self.app, self.environ, start_response)

    def test_empty_content_type(self):
        self.environ['CONTENT_LENGTH'] = '10'
        self.environ['CONTENT_TYPE'] = ''
        self.assertRaisesRegex(webob.exc.HTTPBadRequest,
                               "content-type header required when "
                               "content-length > 0", self.app,
                               self.environ, start_response)

    def test_empty_content_length_and_type_works(self):
        self.environ['CONTENT_LENGTH'] = ''
        self.environ['CONTENT_TYPE'] = ''
        self.app(self.environ, start_response)

    def test_content_length_and_type_works(self):
        self.environ['CONTENT_LENGTH'] = '10'
        self.environ['CONTENT_TYPE'] = 'foo'
        self.app(self.environ, start_response)
