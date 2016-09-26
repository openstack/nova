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

import mock
import routes
import webob

from nova.api.openstack.placement import handler
from nova import test
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
    }


class DispatchTest(test.NoDBTestCase):

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


class MapperTest(test.NoDBTestCase):

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

    def test_405(self):
        environ = _environ(path='/hello', method='POST')
        result = self.mapper.match(environ=environ)
        self.assertEqual(handler.handle_405, result['action'])
        self.assertEqual('GET', result['_methods'])


class PlacementLoggingTest(test.NoDBTestCase):

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
