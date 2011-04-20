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

import json
from nova import test

import routes
import webob

from nova import exception
from nova import wsgi


class Test(test.TestCase):

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


class ControllerTest(test.TestCase):

    class TestRouter(wsgi.Router):

        class TestController(wsgi.Controller):

            _serialization_metadata = {
                'application/xml': {
                    "attributes": {
                        "test": ["id"]}}}

            def show(self, req, id):  # pylint: disable=W0622,C0103
                return {"test": {"id": id}}

        def __init__(self):
            mapper = routes.Mapper()
            mapper.resource("test", "tests", controller=self.TestController())
            wsgi.Router.__init__(self, mapper)

    def test_show(self):
        request = wsgi.Request.blank('/tests/123')
        result = request.get_response(self.TestRouter())
        self.assertEqual(json.loads(result.body), {"test": {"id": "123"}})

    def test_response_content_type_from_accept_xml(self):
        request = webob.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml"
        result = request.get_response(self.TestRouter())
        self.assertEqual(result.headers["Content-Type"], "application/xml")

    def test_response_content_type_from_accept_json(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/json"
        result = request.get_response(self.TestRouter())
        self.assertEqual(result.headers["Content-Type"], "application/json")

    def test_response_content_type_from_query_extension_xml(self):
        request = wsgi.Request.blank('/tests/123.xml')
        result = request.get_response(self.TestRouter())
        self.assertEqual(result.headers["Content-Type"], "application/xml")

    def test_response_content_type_from_query_extension_json(self):
        request = wsgi.Request.blank('/tests/123.json')
        result = request.get_response(self.TestRouter())
        self.assertEqual(result.headers["Content-Type"], "application/json")

    def test_response_content_type_default_when_unsupported(self):
        request = wsgi.Request.blank('/tests/123.unsupported')
        request.headers["Accept"] = "application/unsupported1"
        result = request.get_response(self.TestRouter())
        self.assertEqual(result.status_int, 200)
        self.assertEqual(result.headers["Content-Type"], "application/json")


class RequestTest(test.TestCase):

    def test_request_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123')
        request.body = "<body />"
        self.assertRaises(webob.exc.HTTPBadRequest, request.get_content_type)

    def test_request_content_type_unsupported(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "text/html"
        request.body = "asdf<br />"
        self.assertRaises(webob.exc.HTTPBadRequest, request.get_content_type)

    def test_request_content_type_with_charset(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "application/json; charset=UTF-8"
        request.body = "<body />"
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


class SerializerTest(test.TestCase):

    def test_xml(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_xml = '<servers><a>(2,3)</a></servers>'
        serializer = wsgi.Serializer()
        result = serializer.serialize(input_dict, "application/xml")
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_xml)

    def test_json(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_json = '{"servers":{"a":[2,3]}}'
        serializer = wsgi.Serializer()
        result = serializer.serialize(input_dict, "application/json")
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(result, expected_json)

    def test_unsupported_content_type(self):
        serializer = wsgi.Serializer()
        self.assertRaises(exception.InvalidContentType, serializer.serialize,
                          {}, "text/null")

    def test_deserialize_json(self):
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
        metadata = {}
        serializer = wsgi.Serializer(metadata)
        self.assertEqual(serializer.deserialize(data, "application/json"),
                         as_dict)

    def test_deserialize_xml(self):
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
        metadata = {'application/xml': dict(plurals={'bs': 'b', 'ts': 't'})}
        serializer = wsgi.Serializer(metadata)
        self.assertEqual(serializer.deserialize(xml, "application/xml"),
                         as_dict)

    def test_deserialize_empty_xml(self):
        xml = """<a></a>"""
        as_dict = {"a": {}}
        serializer = wsgi.Serializer()
        self.assertEqual(serializer.deserialize(xml, "application/xml"),
                         as_dict)
