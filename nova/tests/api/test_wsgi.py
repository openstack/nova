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

            def show(self, req, id):  # pylint: disable-msg=W0622,C0103
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


class SerializerTest(unittest.TestCase):

    def match(self, url, accept, expect):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_xml = '<servers><a>(2,3)</a></servers>'
        expected_json = '{"servers":{"a":[2,3]}}'
        req = webob.Request.blank(url, headers=dict(Accept=accept))
        result = wsgi.Serializer(req.environ).to_content_type(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        if expect == 'xml':
            self.assertEqual(result, expected_xml)
        elif expect == 'json':
            self.assertEqual(result, expected_json)
        else:
            raise "Bad expect value"

    def test_basic(self):
        self.match('/servers/4.json', None, expect='json')
        self.match('/servers/4', 'application/json', expect='json')
        self.match('/servers/4', 'application/xml', expect='xml')
        self.match('/servers/4.xml',  None, expect='xml')

    def test_defaults_to_json(self):
        self.match('/servers/4', None, expect='json')
        self.match('/servers/4', 'text/html', expect='json')

    def test_suffix_takes_precedence_over_accept_header(self):
        self.match('/servers/4.xml', 'application/json', expect='xml')
        self.match('/servers/4.xml.', 'application/json', expect='json')

    def test_deserialize(self):
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
        serializer = wsgi.Serializer({}, metadata)
        self.assertEqual(serializer.deserialize(xml), as_dict)

    def test_deserialize_empty_xml(self):
        xml = """<a></a>"""
        as_dict = {"a": {}}
        serializer = wsgi.Serializer({})
        self.assertEqual(serializer.deserialize(xml), as_dict)
