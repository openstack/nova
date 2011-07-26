# vim: tabstop=4 shiftwidth=4 softtabstop=4

import json
import webob

from nova import exception
from nova import test
from nova.api.openstack import wsgi


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

    def test_content_type_from_accept_xml(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/json"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

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
        response = webob.Response()
        serializer.serialize(response, {'v': '123'}, 'asdf')
        self.assertEqual(response.status_int, 200)

    def test_custom(self):
        class Serializer(wsgi.ResponseHeadersSerializer):
            def update(self, response, data):
                response.status_int = 404
                response.headers['X-Custom-Header'] = data['v']
        serializer = Serializer()
        response = webob.Response()
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


class ResponseSerializerTest(test.TestCase):
    def setUp(self):
        class JSONSerializer(object):
            def serialize(self, data, action='default'):
                return 'pew_json'

        class XMLSerializer(object):
            def serialize(self, data, action='default'):
                return 'pew_xml'

        class HeadersSerializer(object):
            def serialize(self, response, data, action):
                response.status_int = 404

        self.body_serializers = {
            'application/json': JSONSerializer(),
            'application/XML': XMLSerializer(),
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

    def test_serialize_response(self):
        response = self.serializer.serialize({}, 'application/json')
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.body, 'pew_json')
        self.assertEqual(response.status_int, 404)

    def test_serialize_response_None(self):
        response = self.serializer.serialize(None, 'application/json')
        print response
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.body, '')
        self.assertEqual(response.status_int, 404)

    def test_serialize_response_dict_to_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.serializer.serialize,
                          {}, 'application/unknown')


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
            'application/XML': XMLDeserializer(),
        }

        self.deserializer = wsgi.RequestDeserializer(self.body_deserializers)

    def tearDown(self):
        pass

    def test_get_deserializer(self):
        expected = self.deserializer.get_body_deserializer('application/json')
        self.assertEqual(expected, self.body_deserializers['application/json'])

    def test_get_deserializer_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.deserializer.get_body_deserializer,
                          'application/unknown')

    def test_get_expected_content_type(self):
        request = wsgi.Request.blank('/')
        request.headers['Accept'] = 'application/json'
        self.assertEqual(self.deserializer.get_expected_content_type(request),
                         'application/json')

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

        resource = wsgi.Resource(Controller())
        actual = resource.dispatch(None, 'index', {'pants': 'off'})
        expected = 'off'
        self.assertEqual(actual, expected)

    def test_dispatch_unknown_controller_action(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        resource = wsgi.Resource(Controller())
        self.assertRaises(AttributeError, resource.dispatch,
                          None, 'create', {})
