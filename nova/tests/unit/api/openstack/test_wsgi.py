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

import inspect

import mock
import webob

from nova.api.openstack import api_version_request as api_version
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova import i18n
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import utils


class RequestTest(test.NoDBTestCase):
    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.body = "<body />"
        self.assertIsNone(request.get_content_type())

    def test_content_type_unsupported(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.headers["Content-Type"] = "text/html"
        request.body = "asdf<br />"
        self.assertRaises(exception.InvalidContentType,
                          request.get_content_type)

    def test_content_type_with_charset(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "application/json; charset=UTF-8"
        result = request.get_content_type()
        self.assertEqual(result, "application/json")

    def test_content_type_accept_default(self):
        request = wsgi.Request.blank('/tests/123.unsupported')
        request.headers["Accept"] = "application/unsupported1"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

    def test_cache_and_retrieve_instances(self):
        request = wsgi.Request.blank('/foo')
        instances = []
        for x in xrange(3):
            instances.append({'uuid': 'uuid%s' % x})
        # Store 2
        request.cache_db_instances(instances[:2])
        # Store 1
        request.cache_db_instance(instances[2])
        self.assertEqual(request.get_db_instance('uuid0'),
                instances[0])
        self.assertEqual(request.get_db_instance('uuid1'),
                instances[1])
        self.assertEqual(request.get_db_instance('uuid2'),
                instances[2])
        self.assertIsNone(request.get_db_instance('uuid3'))
        self.assertEqual(request.get_db_instances(),
                {'uuid0': instances[0],
                 'uuid1': instances[1],
                 'uuid2': instances[2]})

    def test_cache_and_retrieve_compute_nodes(self):
        request = wsgi.Request.blank('/foo')
        compute_nodes = []
        for x in xrange(3):
            compute_nodes.append({'id': 'id%s' % x})
        # Store 2
        request.cache_db_compute_nodes(compute_nodes[:2])
        # Store 1
        request.cache_db_compute_node(compute_nodes[2])
        self.assertEqual(request.get_db_compute_node('id0'),
                compute_nodes[0])
        self.assertEqual(request.get_db_compute_node('id1'),
                compute_nodes[1])
        self.assertEqual(request.get_db_compute_node('id2'),
                compute_nodes[2])
        self.assertIsNone(request.get_db_compute_node('id3'))
        self.assertEqual(request.get_db_compute_nodes(),
                {'id0': compute_nodes[0],
                 'id1': compute_nodes[1],
                 'id2': compute_nodes[2]})

    def test_from_request(self):
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'bogus;q=1.1, en-gb;q=0.7,en-us,en;q=.5,*;q=.7'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_US')

    def test_asterisk(self):
        # asterisk should match first available if there
        # are not any other available matches
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = '*,es;q=.5'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_GB')

    def test_prefix(self):
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'zh'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'zh_CN')

    def test_secondary(self):
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'nn,en-gb;q=.5'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_GB')

    def test_none_found(self):
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'nb-no'
        request.headers = {'Accept-Language': accepted}
        self.assertIs(request.best_match_language(), None)

    def test_no_lang_header(self):
        self.stubs.Set(i18n, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = ''
        request.headers = {'Accept-Language': accepted}
        self.assertIs(request.best_match_language(), None)

    def test_api_version_request_header_none(self):
        request = wsgi.Request.blank('/')
        request.set_api_version_request()
        self.assertEqual(api_version.APIVersionRequest(
            api_version.DEFAULT_API_VERSION), request.api_version_request)

    @mock.patch("nova.api.openstack.api_version_request.max_api_version")
    def test_api_version_request_header(self, mock_maxver):
        mock_maxver.return_value = api_version.APIVersionRequest("2.14")

        request = wsgi.Request.blank('/')
        request.headers = {'X-OpenStack-Compute-API-Version': '2.14'}
        request.set_api_version_request()
        self.assertEqual(api_version.APIVersionRequest("2.14"),
                         request.api_version_request)

    @mock.patch("nova.api.openstack.api_version_request.max_api_version")
    def test_api_version_request_header_latest(self, mock_maxver):
        mock_maxver.return_value = api_version.APIVersionRequest("3.5")

        request = wsgi.Request.blank('/')
        request.headers = {'X-OpenStack-Compute-API-Version': 'latest'}
        request.set_api_version_request()
        self.assertEqual(api_version.APIVersionRequest("3.5"),
                         request.api_version_request)

    def test_api_version_request_header_invalid(self):
        request = wsgi.Request.blank('/')
        request.headers = {'X-OpenStack-Compute-API-Version': '2.1.3'}

        self.assertRaises(exception.InvalidAPIVersionString,
                          request.set_api_version_request)


class ActionDispatcherTest(test.NoDBTestCase):
    def test_dispatch(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        self.assertEqual(serializer.dispatch({}, action='create'), 'pants')

    def test_dispatch_action_None(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        serializer.default = lambda x: 'trousers'
        self.assertEqual(serializer.dispatch({}, action=None), 'trousers')

    def test_dispatch_default(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        serializer.default = lambda x: 'trousers'
        self.assertEqual(serializer.dispatch({}, action='update'), 'trousers')


class DictSerializerTest(test.NoDBTestCase):
    def test_dispatch_default(self):
        serializer = wsgi.DictSerializer()
        self.assertEqual(serializer.serialize({}, 'update'), '')


class JSONDictSerializerTest(test.NoDBTestCase):
    def test_json(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_json = '{"servers":{"a":[2,3]}}'
        serializer = wsgi.JSONDictSerializer()
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_json)


class TextDeserializerTest(test.NoDBTestCase):
    def test_dispatch_default(self):
        deserializer = wsgi.TextDeserializer()
        self.assertEqual(deserializer.deserialize({}, 'update'), {})


class JSONDeserializerTest(test.NoDBTestCase):
    def test_json(self):
        data = """{"a": {
                "a1": "1",
                "a2": "2",
                "bs": ["1", "2", "3", {"c": {"c1": "1"}}],
                "d": {"e": "1"},
                "f": "1"}}"""
        as_dict = {
            'body': {
                'a': {
                    'a1': '1',
                    'a2': '2',
                    'bs': ['1', '2', '3', {'c': {'c1': '1'}}],
                    'd': {'e': '1'},
                    'f': '1',
                },
            },
        }
        deserializer = wsgi.JSONDeserializer()
        self.assertEqual(deserializer.deserialize(data), as_dict)

    def test_json_valid_utf8(self):
        data = """{"server": {"min_count": 1, "flavorRef": "1",
                "name": "\xe6\xa6\x82\xe5\xbf\xb5",
                "imageRef": "10bab10c-1304-47d",
                "max_count": 1}} """
        as_dict = {
            'body': {
                u'server': {
                            u'min_count': 1, u'flavorRef': u'1',
                            u'name': u'\u6982\u5ff5',
                            u'imageRef': u'10bab10c-1304-47d',
                            u'max_count': 1
                           }
                    }
            }
        deserializer = wsgi.JSONDeserializer()
        self.assertEqual(deserializer.deserialize(data), as_dict)

    def test_json_invalid_utf8(self):
        """Send invalid utf-8 to JSONDeserializer."""
        data = """{"server": {"min_count": 1, "flavorRef": "1",
                "name": "\xf0\x28\x8c\x28",
                "imageRef": "10bab10c-1304-47d",
                "max_count": 1}} """

        deserializer = wsgi.JSONDeserializer()
        self.assertRaises(exception.MalformedRequestBody,
                          deserializer.deserialize, data)


class ResourceTest(test.NoDBTestCase):

    def get_req_id_header_name(self, request):
        header_name = 'x-openstack-request-id'
        if utils.get_api_version(request) < 3:
                header_name = 'x-compute-request-id'

        return header_name

    def test_resource_receives_api_version_request_default(self):
        class Controller(object):
            def index(self, req):
                if req.api_version_request != \
                  api_version.APIVersionRequest(
                      api_version.DEFAULT_API_VERSION):
                    raise webob.exc.HTTPInternalServerError()
                return 'success'

        app = fakes.TestRouterV21(Controller())
        req = webob.Request.blank('/tests')
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)

    @mock.patch("nova.api.openstack.api_version_request.max_api_version")
    def test_resource_receives_api_version_request(self, mock_maxver):
        version = "2.5"
        mock_maxver.return_value = api_version.APIVersionRequest(version)

        class Controller(object):
            def index(self, req):
                if req.api_version_request != \
                  api_version.APIVersionRequest(version):
                    raise webob.exc.HTTPInternalServerError()
                return 'success'

        app = fakes.TestRouterV21(Controller())
        req = webob.Request.blank('/tests')
        req.headers = {'X-OpenStack-Compute-API-Version': version}
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)

    def test_resource_receives_api_version_request_invalid(self):
        invalid_version = "2.5.3"

        class Controller(object):
            def index(self, req):
                return 'success'

        app = fakes.TestRouterV21(Controller())
        req = webob.Request.blank('/tests')
        req.headers = {'X-OpenStack-Compute-API-Version': invalid_version}
        response = req.get_response(app)
        self.assertEqual(400, response.status_int)

    def test_resource_call_with_method_get(self):
        class Controller(object):
            def index(self, req):
                return 'success'

        app = fakes.TestRouter(Controller())
        # the default method is GET
        req = webob.Request.blank('/tests')
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)
        req.body = '{"body": {"key": "value"}}'
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)
        req.content_type = 'application/json'
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)

    def test_resource_call_with_method_post(self):
        class Controller(object):
            @extensions.expected_errors(400)
            def create(self, req, body):
                if expected_body != body:
                    msg = "The request body invalid"
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                return "success"
        # verify the method: POST
        app = fakes.TestRouter(Controller())
        req = webob.Request.blank('/tests', method="POST",
                                  content_type='application/json')
        req.body = '{"body": {"key": "value"}}'
        expected_body = {'body': {
            "key": "value"
            }
        }
        response = req.get_response(app)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, 'success')
        # verify without body
        expected_body = None
        req.body = None
        response = req.get_response(app)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, 'success')
        # the body is validated in the controller
        expected_body = {'body': None}
        response = req.get_response(app)
        expected_unsupported_type_body = ('{"badRequest": '
            '{"message": "The request body invalid", "code": 400}}')
        self.assertEqual(response.status_int, 400)
        self.assertEqual(expected_unsupported_type_body, response.body)

    def test_resource_call_with_method_put(self):
        class Controller(object):
            def update(self, req, id, body):
                if expected_body != body:
                    msg = "The request body invalid"
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                return "success"
        # verify the method: PUT
        app = fakes.TestRouter(Controller())
        req = webob.Request.blank('/tests/test_id', method="PUT",
                                  content_type='application/json')
        req.body = '{"body": {"key": "value"}}'
        expected_body = {'body': {
            "key": "value"
            }
        }
        response = req.get_response(app)
        self.assertEqual(response.body, 'success')
        self.assertEqual(response.status_int, 200)
        req.body = None
        expected_body = None
        response = req.get_response(app)
        self.assertEqual(response.status_int, 200)
        # verify no content_type is contained in the request
        req.content_type = None
        req.body = '{"body": {"key": "value"}}'
        response = req.get_response(app)
        expected_unsupported_type_body = ('{"badRequest": '
            '{"message": "Unsupported Content-Type", "code": 400}}')
        self.assertEqual(response.status_int, 400)
        self.assertEqual(expected_unsupported_type_body, response.body)

    def test_resource_call_with_method_delete(self):
        class Controller(object):
            def delete(self, req, id):
                return "success"

        # verify the method: DELETE
        app = fakes.TestRouter(Controller())
        req = webob.Request.blank('/tests/test_id', method="DELETE")
        response = req.get_response(app)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, 'success')
        # ignore the body
        req.body = '{"body": {"key": "value"}}'
        response = req.get_response(app)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, 'success')

    def test_resource_not_authorized(self):
        class Controller(object):
            def index(self, req):
                raise exception.Forbidden()

        req = webob.Request.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(response.status_int, 403)

    def test_dispatch(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, extensions = resource.get_method(None, 'index', None, '')
        actual = resource.dispatch(method, None, {'pants': 'off'})
        expected = 'off'
        self.assertEqual(actual, expected)

    def test_get_method_unknown_controller_method(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(AttributeError, resource.get_method,
                          None, 'create', None, '')

    def test_get_method_action_json(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, extensions = resource.get_method(None, 'action',
                                                 'application/json',
                                                 '{"fooAction": true}')
        self.assertEqual(controller._action_foo, method)

    def test_get_method_action_bad_body(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(exception.MalformedRequestBody, resource.get_method,
                          None, 'action', 'application/json', '{}')

    def test_get_method_unknown_controller_action(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(KeyError, resource.get_method,
                          None, 'action', 'application/json',
                          '{"barAction": true}')

    def test_get_method_action_method(self):
        class Controller():
            def action(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, extensions = resource.get_method(None, 'action',
                                                 'application/xml',
                                                 '<fooAction>true</fooAction')
        self.assertEqual(controller.action, method)

    def test_get_action_args(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        env = {
            'wsgiorg.routing_args': [None, {
                'controller': None,
                'format': None,
                'action': 'update',
                'id': 12,
            }],
        }

        expected = {'action': 'update', 'id': 12}

        self.assertEqual(resource.get_action_args(env), expected)

    def test_get_body_bad_content(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/none'
        request.body = 'foo'

        content_type, body = resource.get_body(request)
        self.assertIsNone(content_type)
        self.assertEqual(body, '')

    def test_get_body_no_content_type(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.body = 'foo'

        content_type, body = resource.get_body(request)
        self.assertIsNone(content_type)
        self.assertEqual(body, 'foo')

    def test_get_body_no_content_body(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/json'
        request.body = ''

        content_type, body = resource.get_body(request)
        self.assertEqual('application/json', content_type)
        self.assertEqual(body, '')

    def test_get_body(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/json'
        request.body = 'foo'

        content_type, body = resource.get_body(request)
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(body, 'foo')

    def test_get_request_id_with_dict_response_body(self):
        class Controller(wsgi.Controller):
            def index(self, req):
                return {'foo': 'bar'}

        req = fakes.HTTPRequest.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertIn('nova.context', req.environ)
        self.assertEqual(response.body, '{"foo": "bar"}')
        self.assertEqual(response.status_int, 200)

    def test_no_request_id_with_str_response_body(self):
        class Controller(wsgi.Controller):
            def index(self, req):
                return 'foo'

        req = fakes.HTTPRequest.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        # NOTE(alaski): This test is really to ensure that a str response
        # doesn't error.  Not having a request_id header is a side effect of
        # our wsgi setup, ideally it would be there.
        expected_header = self.get_req_id_header_name(req)
        self.assertFalse(hasattr(response.headers, expected_header))
        self.assertEqual(response.body, 'foo')
        self.assertEqual(response.status_int, 200)

    def test_get_request_id_no_response_body(self):
        class Controller(object):
            def index(self, req):
                pass

        req = fakes.HTTPRequest.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertIn('nova.context', req.environ)
        self.assertEqual(response.body, '')
        self.assertEqual(response.status_int, 200)

    def test_deserialize_badtype(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(exception.InvalidContentType,
                          resource.deserialize,
                          controller.index, 'application/none', 'foo')

    def test_deserialize_default(self):
        class JSONDeserializer(object):
            def deserialize(self, body):
                return 'json'

        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller, json=JSONDeserializer)

        obj = resource.deserialize(controller.index, 'application/json', 'foo')
        self.assertEqual(obj, 'json')

    def test_register_actions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

            @wsgi.action('barAction')
            def _action_bar(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertEqual({}, resource.wsgi_actions)

        extended = ControllerExtended()
        resource.register_actions(extended)
        self.assertEqual({
                'fooAction': extended._action_foo,
                'barAction': extended._action_bar,
                }, resource.wsgi_actions)

    def test_register_extensions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends
            def index(self, req, resp_obj, pants=None):
                return None

            @wsgi.extends(action='fooAction')
            def _action_foo(self, req, resp, id, body):
                return None

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertEqual({}, resource.wsgi_extensions)
        self.assertEqual({}, resource.wsgi_action_extensions)

        extended = ControllerExtended()
        resource.register_extensions(extended)
        self.assertEqual({'index': [extended.index]}, resource.wsgi_extensions)
        self.assertEqual({'fooAction': [extended._action_foo]},
                         resource.wsgi_action_extensions)

    def test_get_method_extensions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends
            def index(self, req, resp_obj, pants=None):
                return None

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_extensions(extended)
        method, extensions = resource.get_method(None, 'index', None, '')
        self.assertEqual(method, controller.index)
        self.assertEqual(extensions, [extended.index])

    def test_get_method_action_extensions(self):
        class Controller(wsgi.Controller):
            def index(self, req, pants=None):
                return pants

            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends(action='fooAction')
            def _action_foo(self, req, resp_obj, id, body):
                return None

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_extensions(extended)
        method, extensions = resource.get_method(None, 'action',
                                                 'application/json',
                                                 '{"fooAction": true}')
        self.assertEqual(method, controller._action_foo)
        self.assertEqual(extensions, [extended._action_foo])

    def test_get_method_action_whitelist_extensions(self):
        class Controller(wsgi.Controller):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.action('create')
            def _create(self, req, body):
                pass

            @wsgi.action('delete')
            def _delete(self, req, id):
                pass

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_actions(extended)

        method, extensions = resource.get_method(None, 'create',
                                                 'application/json',
                                                 '{"create": true}')
        self.assertEqual(method, extended._create)
        self.assertEqual(extensions, [])

        method, extensions = resource.get_method(None, 'delete', None, None)
        self.assertEqual(method, extended._delete)
        self.assertEqual(extensions, [])

    def test_pre_process_extensions_regular(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return None

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        self.assertEqual(called, [])
        self.assertIsNone(response)
        self.assertEqual(list(post), [extension2, extension1])

    def test_pre_process_extensions_generator(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            called.append('pre1')
            yield
            called.append('post1')

        def extension2(req):
            called.append('pre2')
            yield
            called.append('post2')

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        post = list(post)
        self.assertEqual(called, ['pre1', 'pre2'])
        self.assertIsNone(response)
        self.assertEqual(len(post), 2)
        self.assertTrue(inspect.isgenerator(post[0]))
        self.assertTrue(inspect.isgenerator(post[1]))

        for gen in post:
            try:
                gen.send(None)
            except StopIteration:
                continue

        self.assertEqual(called, ['pre1', 'pre2', 'post2', 'post1'])

    def test_pre_process_extensions_generator_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            called.append('pre1')
            yield 'foo'

        def extension2(req):
            called.append('pre2')

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        self.assertEqual(called, ['pre1'])
        self.assertEqual(response, 'foo')
        self.assertEqual(post, [])

    def test_post_process_extensions_regular(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return None

        response = resource.post_process_extensions([extension2, extension1],
                                                    None, None, {})
        self.assertEqual(called, [2, 1])
        self.assertIsNone(response)

    def test_post_process_extensions_regular_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return 'foo'

        response = resource.post_process_extensions([extension2, extension1],
                                                    None, None, {})
        self.assertEqual(called, [2])
        self.assertEqual(response, 'foo')

    def test_post_process_extensions_generator(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            yield
            called.append(1)

        def extension2(req):
            yield
            called.append(2)

        ext1 = extension1(None)
        ext1.next()
        ext2 = extension2(None)
        ext2.next()

        response = resource.post_process_extensions([ext2, ext1],
                                                    None, None, {})

        self.assertEqual(called, [2, 1])
        self.assertIsNone(response)

    def test_post_process_extensions_generator_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            yield
            called.append(1)

        def extension2(req):
            yield
            called.append(2)
            yield 'foo'

        ext1 = extension1(None)
        ext1.next()
        ext2 = extension2(None)
        ext2.next()

        response = resource.post_process_extensions([ext2, ext1],
                                                    None, None, {})

        self.assertEqual(called, [2])
        self.assertEqual(response, 'foo')

    def test_resource_exception_handler_type_error(self):
        # A TypeError should be translated to a Fault/HTTP 400.
        def foo(a,):
            return a

        try:
            with wsgi.ResourceExceptionHandler():
                foo()  # generate a TypeError
            self.fail("Should have raised a Fault (HTTP 400)")
        except wsgi.Fault as fault:
            self.assertEqual(400, fault.status_int)

    def test_resource_headers_are_utf8(self):
        resp = webob.Response(status_int=202)
        resp.headers['x-header1'] = 1
        resp.headers['x-header2'] = u'header2'
        resp.headers['x-header3'] = u'header3'

        class Controller(object):
            def index(self, req):
                return resp

        req = webob.Request.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)

        for hdr, val in response.headers.iteritems():
            # All headers must be utf8
            self.assertIsInstance(hdr, str)
            self.assertIsInstance(val, str)
        self.assertEqual(response.headers['x-header1'], '1')
        self.assertEqual(response.headers['x-header2'], 'header2')
        self.assertEqual(response.headers['x-header3'], 'header3')

    def test_resource_valid_utf8_body(self):
        class Controller(object):
            def update(self, req, id, body):
                return body

        req = webob.Request.blank('/tests/test_id', method="PUT")
        body = """ {"name": "\xe6\xa6\x82\xe5\xbf\xb5" } """
        expected_body = '{"name": "\\u6982\\u5ff5"}'
        req.body = body
        req.headers['Content-Type'] = 'application/json'
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(response.body, expected_body)
        self.assertEqual(response.status_int, 200)

    def test_resource_invalid_utf8(self):
        class Controller(object):
            def update(self, req, id, body):
                return body

        req = webob.Request.blank('/tests/test_id', method="PUT")
        body = """ {"name": "\xf0\x28\x8c\x28" } """
        req.body = body
        req.headers['Content-Type'] = 'application/json'
        app = fakes.TestRouter(Controller())
        self.assertRaises(UnicodeDecodeError, req.get_response, app)


class ResponseObjectTest(test.NoDBTestCase):
    def test_default_code(self):
        robj = wsgi.ResponseObject({})
        self.assertEqual(robj.code, 200)

    def test_modified_code(self):
        robj = wsgi.ResponseObject({})
        robj._default_code = 202
        self.assertEqual(robj.code, 202)

    def test_override_default_code(self):
        robj = wsgi.ResponseObject({}, code=404)
        self.assertEqual(robj.code, 404)

    def test_override_modified_code(self):
        robj = wsgi.ResponseObject({}, code=404)
        robj._default_code = 202
        self.assertEqual(robj.code, 404)

    def test_set_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        self.assertEqual(robj.headers, {'header': 'foo'})

    def test_get_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        self.assertEqual(robj['hEADER'], 'foo')

    def test_del_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        del robj['hEADER']
        self.assertNotIn('header', robj.headers)

    def test_header_isolation(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        hdrs = robj.headers
        hdrs['hEADER'] = 'bar'
        self.assertEqual(robj['hEADER'], 'foo')

    def test_default_serializers(self):
        robj = wsgi.ResponseObject({})
        self.assertEqual(robj.serializers, {})

    def test_bind_serializers(self):
        robj = wsgi.ResponseObject({}, json='foo')
        robj._bind_method_serializers(dict(xml='bar', json='baz'))
        self.assertEqual(robj.serializers, dict(xml='bar', json='foo'))

    def test_get_serializer(self):
        robj = wsgi.ResponseObject({}, json='json', xml='xml', atom='atom')
        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            _mtype, serializer = robj.get_serializer(content_type)
            self.assertEqual(serializer, mtype)

    def test_get_serializer_defaults(self):
        robj = wsgi.ResponseObject({})
        default_serializers = dict(json='json', xml='xml', atom='atom')
        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            self.assertRaises(exception.InvalidContentType,
                              robj.get_serializer, content_type)
            _mtype, serializer = robj.get_serializer(content_type,
                                                     default_serializers)
            self.assertEqual(serializer, mtype)

    def test_serialize(self):
        class JSONSerializer(object):
            def serialize(self, obj):
                return 'json'

        class AtomSerializer(object):
            def serialize(self, obj):
                return 'atom'

        robj = wsgi.ResponseObject({}, code=202,
                                   json=JSONSerializer,
                                   atom=AtomSerializer)
        robj['X-header1'] = 'header1'
        robj['X-header2'] = 'header2'
        robj['X-header3'] = 3
        robj['X-header-unicode'] = u'header-unicode'

        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            request = wsgi.Request.blank('/tests/123')
            response = robj.serialize(request, content_type)

            self.assertEqual(response.headers['Content-Type'], content_type)
            for hdr, val in response.headers.iteritems():
                # All headers must be utf8
                self.assertIsInstance(hdr, str)
                self.assertIsInstance(val, str)
            self.assertEqual(response.headers['X-header1'], 'header1')
            self.assertEqual(response.headers['X-header2'], 'header2')
            self.assertEqual(response.headers['X-header3'], '3')
            self.assertEqual(response.status_int, 202)
            self.assertEqual(response.body, mtype)


class ValidBodyTest(test.NoDBTestCase):

    def setUp(self):
        super(ValidBodyTest, self).setUp()
        self.controller = wsgi.Controller()

    def test_is_valid_body(self):
        body = {'foo': {}}
        self.assertTrue(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_none(self):
        wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body(None, 'foo'))

    def test_is_valid_body_empty(self):
        wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body({}, 'foo'))

    def test_is_valid_body_no_entity(self):
        wsgi.Resource(controller=None)
        body = {'bar': {}}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_malformed_entity(self):
        wsgi.Resource(controller=None)
        body = {'foo': 'bar'}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))
