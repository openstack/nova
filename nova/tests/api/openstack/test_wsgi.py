# vim: tabstop=4 shiftwidth=4 softtabstop=4

import json
import webob

from nova import exception
from nova import test
from nova import utils
from nova.api.openstack import wsgi
import nova.context


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
        request.headers["Accept"] = \
            "application/json; q=0.3, application/xml; q=0.9"
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


class ResponseHeadersSerializerTest(test.TestCase):
    def test_default(self):
        serializer = wsgi.ResponseHeadersSerializer()
        context = nova.context.get_admin_context()
        req = webob.Request.blank('/', environ={'nova.context': context})
        response = webob.Response(request=req)
        serializer.serialize(response, {'v': '123'}, 'asdf')
        self.assertEqual(response.status_int, 200)

    def test_custom(self):
        class Serializer(wsgi.ResponseHeadersSerializer):
            def update(self, response, data):
                response.status_int = 404
                response.headers['X-Custom-Header'] = data['v']
        serializer = Serializer()
        context = nova.context.get_admin_context()
        req = webob.Request.blank('/', environ={'nova.context': context})
        response = webob.Response(request=req)
        serializer.serialize(response, {'v': '123'}, 'update')
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.headers['X-Custom-Header'], '123')


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
        xml = """<a></a>"""
        as_dict = {"body": {"a": {}}}
        deserializer = wsgi.XMLDeserializer()
        self.assertEqual(deserializer.deserialize(xml), as_dict)


class RequestHeadersDeserializerTest(test.TestCase):
    def test_default(self):
        deserializer = wsgi.RequestHeadersDeserializer()
        req = wsgi.Request.blank('/')
        self.assertEqual(deserializer.deserialize(req, 'asdf'), {})

    def test_custom(self):
        class Deserializer(wsgi.RequestHeadersDeserializer):
            def update(self, request):
                return {'a': request.headers['X-Custom-Header']}
        deserializer = Deserializer()
        req = wsgi.Request.blank('/')
        req.headers['X-Custom-Header'] = 'b'
        self.assertEqual(deserializer.deserialize(req, 'update'), {'a': 'b'})


class ResponseHeadersSerializerTest(test.TestCase):
    def test_request_id(self):
        serializer = wsgi.ResponseHeadersSerializer()
        context = nova.context.get_admin_context()
        req = webob.Request.blank('/', environ={'nova.context': context})
        res = webob.Response(request=req)
        serializer.serialize(res, {}, 'foo')
        self.assertTrue(
            utils.is_uuid_like(res.headers['X-Compute-Request-Id']))


class JSONSerializer(object):
    def serialize(self, data, action='default'):
        return 'pew_json'


class XMLSerializer(object):
    def serialize(self, data, action='default'):
        return 'pew_xml'


class HeadersSerializer(object):
    def serialize(self, response, data, action):
        response.status_int = 404


class ResponseSerializerTest(test.TestCase):
    def setUp(self):
        self.body_serializers = {
            'application/json': JSONSerializer(),
            'application/xml': XMLSerializer(),
        }

        self.serializer = wsgi.ResponseSerializer(self.body_serializers,
                                                  HeadersSerializer())

    def tearDown(self):
        pass

    def test_get_serializer(self):
        ctype = 'application/json'
        self.assertEqual(self.serializer.get_body_serializer(ctype),
                         self.body_serializers[ctype])

    def test_get_serializer_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.serializer.get_body_serializer,
                          'application/unknown')

    def test_serialize_response_json(self):
        for content_type in ('application/json',
                             'application/vnd.openstack.compute+json'):
            request = wsgi.Request.blank('/')
            response = self.serializer.serialize(request, {}, content_type)
            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.body, 'pew_json')
            self.assertEqual(response.status_int, 404)

    def test_serialize_response_xml(self):
        for content_type in ('application/xml',
                             'application/vnd.openstack.compute+xml'):
            request = wsgi.Request.blank('/')
            response = self.serializer.serialize(request, {}, content_type)
            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.body, 'pew_xml')
            self.assertEqual(response.status_int, 404)

    def test_serialize_response_None(self):
        request = wsgi.Request.blank('/')
        response = self.serializer.serialize(request, None, 'application/json')
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.body, '')
        self.assertEqual(response.status_int, 404)

    def test_serialize_response_dict_to_unknown_content_type(self):
        request = wsgi.Request.blank('/')
        self.assertRaises(exception.InvalidContentType,
                          self.serializer.serialize,
                          request, {}, 'application/unknown')


class LazySerializationTest(test.TestCase):
    def setUp(self):
        self.body_serializers = {
            'application/json': JSONSerializer(),
            'application/xml': XMLSerializer(),
        }

        self.serializer = wsgi.ResponseSerializer(self.body_serializers,
                                                  HeadersSerializer())

    def tearDown(self):
        pass

    def test_serialize_response_json(self):
        for content_type in ('application/json',
                             'application/vnd.openstack.compute+json'):
            request = wsgi.Request.blank('/')
            request.environ['nova.lazy_serialize'] = True
            response = self.serializer.serialize(request, {}, content_type)
            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.status_int, 404)
            body = json.loads(response.body)
            self.assertEqual(body, {})
            serializer = request.environ['nova.serializer']
            self.assertEqual(serializer.serialize(body), 'pew_json')

    def test_serialize_response_xml(self):
        for content_type in ('application/xml',
                             'application/vnd.openstack.compute+xml'):
            request = wsgi.Request.blank('/')
            request.environ['nova.lazy_serialize'] = True
            response = self.serializer.serialize(request, {}, content_type)
            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.status_int, 404)
            body = json.loads(response.body)
            self.assertEqual(body, {})
            serializer = request.environ['nova.serializer']
            self.assertEqual(serializer.serialize(body), 'pew_xml')

    def test_serialize_response_None(self):
        request = wsgi.Request.blank('/')
        request.environ['nova.lazy_serialize'] = True
        response = self.serializer.serialize(request, None, 'application/json')
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.body, '')


class RequestDeserializerTest(test.TestCase):
    def setUp(self):
        class JSONDeserializer(object):
            def deserialize(self, data, action='default'):
                return 'pew_json'

        class XMLDeserializer(object):
            def deserialize(self, data, action='default'):
                return 'pew_xml'

        self.body_deserializers = {
            'application/json': JSONDeserializer(),
            'application/xml': XMLDeserializer(),
        }

        self.deserializer = wsgi.RequestDeserializer(self.body_deserializers)

    def tearDown(self):
        pass

    def test_get_deserializer(self):
        ctype = 'application/json'
        expected = self.deserializer.get_body_deserializer(ctype)
        self.assertEqual(expected, self.body_deserializers[ctype])

    def test_get_deserializer_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.deserializer.get_body_deserializer,
                          'application/unknown')

    def test_get_expected_content_type(self):
        ctype = 'application/json'
        request = wsgi.Request.blank('/')
        request.headers['Accept'] = ctype
        self.assertEqual(self.deserializer.get_expected_content_type(request),
                         ctype)

    def test_get_action_args(self):
        env = {
            'wsgiorg.routing_args': [None, {
                'controller': None,
                'format': None,
                'action': 'update',
                'id': 12,
            }],
        }

        expected = {'action': 'update', 'id': 12}

        self.assertEqual(self.deserializer.get_action_args(env), expected)

    def test_deserialize(self):
        def fake_get_routing_args(request):
            return {'action': 'create'}
        self.deserializer.get_action_args = fake_get_routing_args

        request = wsgi.Request.blank('/')
        request.headers['Accept'] = 'application/xml'

        deserialized = self.deserializer.deserialize(request)
        expected = ('create', {}, 'application/xml')

        self.assertEqual(expected, deserialized)


class ResourceTest(test.TestCase):
    def test_dispatch(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        method = resource.get_method(None, 'index')
        actual = resource.dispatch(method, None, {'pants': 'off'})
        expected = 'off'
        self.assertEqual(actual, expected)

    def test_get_method_unknown_controller_action(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(AttributeError, resource.get_method,
                          None, 'create')

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
            serializer = robj.get_serializer(content_type)
            self.assertEqual(serializer, mtype)

    def test_get_serializer_defaults(self):
        robj = wsgi.ResponseObject({})
        default_serializers = dict(json='json', xml='xml', atom='atom')
        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            self.assertRaises(exception.InvalidContentType,
                              robj.get_serializer, content_type)
            serializer = robj.get_serializer(content_type,
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

        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            request = wsgi.Request.blank('/tests/123')
            response = robj.serialize(request, content_type)

            self.assertEqual(response.headers['Content-Type'], content_type)
            self.assertEqual(response.headers['X-header1'], 'header1')
            self.assertEqual(response.headers['X-header2'], 'header2')
            self.assertEqual(response.status_int, 202)
            self.assertEqual(response.body, mtype)
