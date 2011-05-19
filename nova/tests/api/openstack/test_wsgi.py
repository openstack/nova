# vim: tabstop=4 shiftwidth=4 softtabstop=4

import json
import webob

from nova import exception
from nova import test
from nova.api.openstack import wsgi


class RequestTest(test.TestCase):
    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123')
        request.body = "<body />"
        self.assertRaises(exception.InvalidContentType,
                          request.get_content_type)

    def test_content_type_unsupported(self):
        request = wsgi.Request.blank('/tests/123')
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


class SerializationTest(test.TestCase):
    def test_xml(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_xml = '<serversxmlns="asdf"><a>(2,3)</a></servers>'
        xmlns = "testing xmlns"
        serializer = wsgi.XMLSerializer(xmlns="asdf")
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_xml)

    def test_json(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_json = '{"servers":{"a":[2,3]}}'
        serializer = wsgi.JSONSerializer()
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_json)


class DeserializationTest(test.TestCase):
    def test_json(self):
        data = """{"a": {
                "a1": "1",
                "a2": "2",
                "bs": ["1", "2", "3", {"c": {"c1": "1"}}],
                "d": {"e": "1"},
                "f": "1"}}"""
        as_dict = dict(a={
                'a1': '1',
                'a2': '2',
                'bs': ['1', '2', '3', {'c': dict(c1='1')}],
                'd': {'e': '1'},
                'f': '1'})
        deserializer = wsgi.JSONDeserializer()
        self.assertEqual(deserializer.deserialize(data), as_dict)

    def test_xml(self):
        xml = """
            <a a1="1" a2="2">
              <bs><b>1</b><b>2</b><b>3</b><b><c c1="1"/></b></bs>
              <d><e>1</e></d>
              <f>1</f>
            </a>
            """.strip()
        as_dict = dict(a={
                'a1': '1',
                'a2': '2',
                'bs': ['1', '2', '3', {'c': dict(c1='1')}],
                'd': {'e': '1'},
                'f': '1'})
        metadata = {'plurals': {'bs': 'b', 'ts': 't'}}
        deserializer = wsgi.XMLDeserializer(metadata=metadata)
        self.assertEqual(deserializer.deserialize(xml), as_dict)

    def test_xml_empty(self):
        xml = """<a></a>"""
        as_dict = {"a": {}}
        deserializer = wsgi.XMLDeserializer()
        self.assertEqual(deserializer.deserialize(xml), as_dict)


class ResourceSerializerTest(test.TestCase):
    def setUp(self):
        class JSONSerializer(object):
            def serialize(self, data):
                return 'pew_json'

        class XMLSerializer(object):
            def serialize(self, data):
                return 'pew_xml'

        self.serializers = {
            'application/json': JSONSerializer(),
            'application/XML': XMLSerializer(),
        }

        self.resource = wsgi.Resource(None, serializers=self.serializers)

    def tearDown(self):
        pass

    def test_get_serializer(self):
        self.assertEqual(self.resource.get_serializer('application/json'),
                         self.serializers['application/json'])

    def test_get_serializer_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.resource.get_serializer,
                          'application/unknown')

    def test_serialize_response_dict(self):
        response = self.resource.serialize_response('application/json', {})
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.body, 'pew_json')

    def test_serialize_response_non_dict(self):
        response = self.resource.serialize_response('application/json', 'a')
        self.assertEqual(response, 'a')

    def test_serialize_response_dict_to_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.resource.serialize_response,
                          'application/unknown', {})

    def test_serialize_response_non_dict_to_unknown_content_type(self):
        response = self.resource.serialize_response('application/unknown', 'a')
        self.assertEqual(response, 'a')


class ResourceDeserializerTest(test.TestCase):
    def setUp(self):
        class JSONDeserializer(object):
            def deserialize(self, data):
                return 'pew_json'

        class XMLDeserializer(object):
            def deserialize(self, data):
                return 'pew_xml'

        self.deserializers = {
            'application/json': JSONDeserializer(),
            'application/XML': XMLDeserializer(),
        }

        self.resource = wsgi.Resource(None, deserializers=self.deserializers)

    def tearDown(self):
        pass

    def test_get_deserializer(self):
        self.assertEqual(self.resource.get_deserializer('application/json'),
                         self.deserializers['application/json'])

    def test_get_deserializer_unknown_content_type(self):
        self.assertRaises(exception.InvalidContentType,
                          self.resource.get_deserializer,
                          'application/unknown')

    def test_get_expected_content_type(self):
        request = wsgi.Request.blank('/')
        request.headers['Accept'] = 'application/json'
        self.assertEqual(self.resource.get_expected_content_type(request),
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

        self.assertEqual(self.resource.get_action_args(env), expected)

    def test_deserialize_request(self):
        def fake_get_routing_args(request):
            return {'action': 'create'}
        self.resource.get_action_args = fake_get_routing_args

        request = wsgi.Request.blank('/')
        request.headers['Accept'] = 'application/xml'

        deserialized = self.resource.deserialize_request(request)
        expected = ('create', {}, 'application/xml')

        self.assertEqual(expected, deserialized)
