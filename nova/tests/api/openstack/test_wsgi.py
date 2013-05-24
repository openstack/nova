# vim: tabstop=4 shiftwidth=4 softtabstop=4

import inspect
import webob

from nova.api.openstack import wsgi
from nova import exception
from nova.openstack.common import gettextutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import utils


class RequestTest(test.TestCase):
    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.body = "<body />"
        self.assertEqual(None, request.get_content_type())

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

    def test_content_type_from_accept(self):
        for content_type in ('application/xml',
                             'application/vnd.openstack.compute+xml',
                             'application/json',
                             'application/vnd.openstack.compute+json'):
            request = wsgi.Request.blank('/tests/123')
            request.headers["Accept"] = content_type
            result = request.best_match_content_type()
            self.assertEqual(result, content_type)

    def test_content_type_from_accept_best(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml, application/json"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = ("application/json; q=0.3, "
                                     "application/xml; q=0.9")
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

    def test_content_type_from_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

        request = wsgi.Request.blank('/tests/123.json')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

        request = wsgi.Request.blank('/tests/123.invalid')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

    def test_content_type_accept_and_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        request.headers["Accept"] = "application/json"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

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
        self.assertEqual(request.get_db_instance('uuid3'), None)
        self.assertEqual(request.get_db_instances(),
                {'uuid0': instances[0],
                 'uuid1': instances[1],
                 'uuid2': instances[2]})

    def test_from_request(self):
        self.stubs.Set(gettextutils, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'bogus;q=1.1, en-gb;q=0.7,en-us,en;q=.5,*;q=.7'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_US')

    def test_asterisk(self):
        # asterisk should match first available if there
        # are not any other available matches
        self.stubs.Set(gettextutils, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = '*,es;q=.5'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_GB')

    def test_prefix(self):
        self.stubs.Set(gettextutils, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'zh'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'zh_CN')

    def test_secondary(self):
        self.stubs.Set(gettextutils, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'nn,en-gb;q=.5'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_GB')

    def test_none_found(self):
        self.stubs.Set(gettextutils, 'get_available_languages',
                       fakes.fake_get_available_languages)

        request = wsgi.Request.blank('/')
        accepted = 'nb-no'
        request.headers = {'Accept-Language': accepted}
        self.assertEqual(request.best_match_language(), 'en_US')


class ActionDispatcherTest(test.TestCase):
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


class DictSerializerTest(test.TestCase):
    def test_dispatch_default(self):
        serializer = wsgi.DictSerializer()
        self.assertEqual(serializer.serialize({}, 'update'), '')


class XMLDictSerializerTest(test.TestCase):
    def test_xml(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_xml = '<serversxmlns="asdf"><a>(2,3)</a></servers>'
        serializer = wsgi.XMLDictSerializer(xmlns="asdf")
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_xml)


class JSONDictSerializerTest(test.TestCase):
    def test_json(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_json = '{"servers":{"a":[2,3]}}'
        serializer = wsgi.JSONDictSerializer()
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_json)


class TextDeserializerTest(test.TestCase):
    def test_dispatch_default(self):
        deserializer = wsgi.TextDeserializer()
        self.assertEqual(deserializer.deserialize({}, 'update'), {})


class JSONDeserializerTest(test.TestCase):
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
        """ Send invalid utf-8 to JSONDeserializer"""
        data = """{"server": {"min_count": 1, "flavorRef": "1",
                "name": "\xf0\x28\x8c\x28",
                "imageRef": "10bab10c-1304-47d",
                "max_count": 1}} """

        deserializer = wsgi.JSONDeserializer()
        self.assertRaises(exception.MalformedRequestBody,
                          deserializer.deserialize, data)


class XMLDeserializerTest(test.TestCase):
    def test_xml(self):
        xml = """
            <a a1="1" a2="2">
              <bs><b>1</b><b>2</b><b>3</b><b><c c1="1"/></b></bs>
              <d><e>1</e></d>
              <f>1</f>
            </a>
            """.strip()
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
        metadata = {'plurals': {'bs': 'b', 'ts': 't'}}
        deserializer = wsgi.XMLDeserializer(metadata=metadata)
        self.assertEqual(deserializer.deserialize(xml), as_dict)

    def test_xml_empty(self):
        xml = '<a></a>'
        as_dict = {"body": {"a": {}}}
        deserializer = wsgi.XMLDeserializer()
        self.assertEqual(deserializer.deserialize(xml), as_dict)

    def test_xml_valid_utf8(self):
        xml = """ <a><name>\xe6\xa6\x82\xe5\xbf\xb5</name></a> """
        deserializer = wsgi.XMLDeserializer()
        as_dict = {'body': {u'a': {u'name': u'\u6982\u5ff5'}}}
        self.assertEqual(deserializer.deserialize(xml), as_dict)

    def test_xml_invalid_utf8(self):
        """ Send invalid utf-8 to XMLDeserializer"""
        xml = """ <a><name>\xf0\x28\x8c\x28</name></a> """
        deserializer = wsgi.XMLDeserializer()
        self.assertRaises(exception.MalformedRequestBody,
                         deserializer.deserialize, xml)


class ResourceTest(test.TestCase):
    def test_resource_call(self):
        class Controller(object):
            def index(self, req):
                return 'off'

        req = webob.Request.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(response.body, 'off')
        self.assertEqual(response.status_int, 200)

    def test_resource_not_authorized(self):
        class Controller(object):
            def index(self, req):
                raise exception.NotAuthorized()

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

    def test_get_method_action_xml(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, extensions = resource.get_method(None, 'action',
                                                 'application/xml',
                                                 '<fooAction>true</fooAction>')
        self.assertEqual(controller._action_foo, method)

    def test_get_method_action_corrupt_xml(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(
                exception.MalformedRequestBody,
                resource.get_method,
                None, 'action',
                'application/xml',
                utils.killer_xml_body())

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
        self.assertEqual(content_type, None)
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
        self.assertEqual(content_type, None)
        self.assertEqual(body, '')

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
        self.assertEqual(content_type, None)
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
        context = req.environ['nova.context']
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(response.headers['x-compute-request-id'],
                context.request_id)
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
        self.assertFalse(hasattr(response.headers, 'x-compute-request-id'))
        self.assertEqual(response.body, 'foo')
        self.assertEqual(response.status_int, 200)

    def test_get_request_id_no_response_body(self):
        class Controller(object):
            def index(self, req):
                pass

        req = fakes.HTTPRequest.blank('/tests')
        context = req.environ['nova.context']
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(response.headers['x-compute-request-id'],
                context.request_id)
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

        class XMLDeserializer(object):
            def deserialize(self, body):
                return 'xml'

        class Controller(object):
            @wsgi.deserializers(xml=XMLDeserializer)
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller, json=JSONDeserializer)

        obj = resource.deserialize(controller.index, 'application/json', 'foo')
        self.assertEqual(obj, 'json')

    def test_deserialize_decorator(self):
        class JSONDeserializer(object):
            def deserialize(self, body):
                return 'json'

        class XMLDeserializer(object):
            def deserialize(self, body):
                return 'xml'

        class Controller(object):
            @wsgi.deserializers(xml=XMLDeserializer)
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller, json=JSONDeserializer)

        obj = resource.deserialize(controller.index, 'application/xml', 'foo')
        self.assertEqual(obj, 'xml')

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
        self.assertEqual(response, None)
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
            resp_obj = yield
            called.append('post1')

        def extension2(req):
            called.append('pre2')
            resp_obj = yield
            called.append('post2')

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        post = list(post)
        self.assertEqual(called, ['pre1', 'pre2'])
        self.assertEqual(response, None)
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
        self.assertEqual(response, None)

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
            resp_obj = yield
            called.append(1)

        def extension2(req):
            resp_obj = yield
            called.append(2)

        ext1 = extension1(None)
        ext1.next()
        ext2 = extension2(None)
        ext2.next()

        response = resource.post_process_extensions([ext2, ext1],
                                                    None, None, {})

        self.assertEqual(called, [2, 1])
        self.assertEqual(response, None)

    def test_post_process_extensions_generator_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            resp_obj = yield
            called.append(1)

        def extension2(req):
            resp_obj = yield
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

    def test_resource_valid_utf8_body(self):
        class Controller(object):
            def index(self, req, body):
                return body

        req = webob.Request.blank('/tests')
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
            def index(self, req, body):
                return body

        req = webob.Request.blank('/tests')
        body = """ {"name": "\xf0\x28\x8c\x28" } """
        req.body = body
        req.headers['Content-Type'] = 'application/json'
        app = fakes.TestRouter(Controller())
        self.assertRaises(UnicodeDecodeError, req.get_response, app)


class ResponseObjectTest(test.TestCase):
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
        self.assertFalse('header' in robj.headers)

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

        class XMLSerializer(object):
            def serialize(self, obj):
                return 'xml'

        class AtomSerializer(object):
            def serialize(self, obj):
                return 'atom'

        robj = wsgi.ResponseObject({}, code=202,
                                   json=JSONSerializer,
                                   xml=XMLSerializer,
                                   atom=AtomSerializer)
        robj['X-header1'] = 'header1'
        robj['X-header2'] = 'header2'
        robj['X-header3'] = 3

        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            request = wsgi.Request.blank('/tests/123')
            response = robj.serialize(request, content_type)

            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.headers['X-header1'], 'header1')
            self.assertEqual(response.headers['X-header2'], 'header2')
            self.assertEqual(response.headers['X-header3'], '3')
            self.assertEqual(response.status_int, 202)
            self.assertEqual(response.body, mtype)


class ValidBodyTest(test.TestCase):

    def setUp(self):
        super(ValidBodyTest, self).setUp()
        self.controller = wsgi.Controller()

    def test_is_valid_body(self):
        body = {'foo': {}}
        self.assertTrue(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_none(self):
        resource = wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body(None, 'foo'))

    def test_is_valid_body_empty(self):
        resource = wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body({}, 'foo'))

    def test_is_valid_body_no_entity(self):
        resource = wsgi.Resource(controller=None)
        body = {'bar': {}}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_malformed_entity(self):
        resource = wsgi.Resource(controller=None)
        body = {'foo': 'bar'}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))
