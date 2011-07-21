# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import json
import os.path
import stubout
import unittest
import webob
from xml.etree import ElementTree

from nova import context
from nova import flags
from nova.api import openstack
from nova.api.openstack import extensions
from nova.api.openstack import flavors
from nova.api.openstack import wsgi
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS

response_body = "Try to say this Mr. Knox, sir..."


class StubController(object):

    def __init__(self, body):
        self.body = body

    def index(self, req):
        return self.body


class StubExtensionManager(object):

    def __init__(self, resource_ext=None, action_ext=None, request_ext=None):
        self.resource_ext = resource_ext
        self.action_ext = action_ext
        self.request_ext = request_ext

    def get_name(self):
        return "Tweedle Beetle Extension"

    def get_alias(self):
        return "TWDLBETL"

    def get_description(self):
        return "Provides access to Tweedle Beetles"

    def get_resources(self):
        resource_exts = []
        if self.resource_ext:
            resource_exts.append(self.resource_ext)
        return resource_exts

    def get_actions(self):
        action_exts = []
        if self.action_ext:
            action_exts.append(self.action_ext)
        return action_exts

    def get_request_extensions(self):
        request_extensions = []
        if self.request_ext:
            request_extensions.append(self.request_ext)
        return request_extensions


class ExtensionControllerTest(unittest.TestCase):

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(
            os.path.dirname(__file__), "extensions")

    def test_list_extensions_json(self):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/extensions")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)

        # Make sure we have all the extensions.
        data = json.loads(response.body)
        names = [x['name'] for x in data['extensions']]
        names.sort()
        self.assertEqual(names, ["FlavorExtraSpecs", "Floating_ips",
            "Fox In Socks", "Hosts", "Multinic", "Volumes"])

        # Make sure that at least Fox in Sox is correct.
        (fox_ext,) = [
            x for x in data['extensions'] if x['alias'] == 'FOXNSOX']
        self.assertEqual(fox_ext, {
                "namespace" : "http://www.fox.in.socks/api/ext/pie/v1.0",
                "name" : "Fox In Socks",
                "updated" : "2011-01-22T13:25:27-06:00",
                "description" : "The Fox In Socks Extension",
                "alias" : "FOXNSOX",
                "links" : []
            }
        )

    def test_get_extension_json(self):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/extensions/FOXNSOX")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)

        data = json.loads(response.body)
        self.assertEqual(data['extension'], {
                "namespace" : "http://www.fox.in.socks/api/ext/pie/v1.0",
                "name" : "Fox In Socks",
                "updated" : "2011-01-22T13:25:27-06:00",
                "description" : "The Fox In Socks Extension",
                "alias" : "FOXNSOX",
                "links" : []
            }
        )

    def test_get_extension_xml(self):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/extensions/FOXNSOX")
        request.accept = "application/xml"
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        print response.body

        elem = ElementTree.XML(response.body.replace("  ", ""))
        self.assertEqual(elem.get('alias'), 'FOXNSOX')
        self.assertEqual(elem.get('name'), 'Fox In Socks')
        self.assertEqual(elem.get('namespace'),
            'http://www.fox.in.socks/api/ext/pie/v1.0')
        self.assertEqual(elem.get('updated'), '2011-01-22T13:25:27-06:00')
        ns = "{http://docs.openstack.org/compute/api/v1.1}"
        self.assertEqual(elem.findtext('{0}description'.format(ns)),
            'The Fox In Socks Extension')


class ResourceExtensionTest(unittest.TestCase):

    def test_no_extension_present(self):
        manager = StubExtensionManager(None)
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/blah")
        response = request.get_response(ext_midware)
        self.assertEqual(404, response.status_int)

    def test_get_resources(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/tweedles")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_get_resources_with_controller(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/tweedles")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)


class InvalidExtension(object):
    def get_alias(self):
        return "THIRD"


class ExtensionManagerTest(unittest.TestCase):

    response_body = "Try to say this Mr. Knox, sir..."

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def test_get_resources(self):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/foxnsocks")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_invalid_extensions(self):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        ext_mgr = ext_midware.ext_mgr
        ext_mgr.add_extension(InvalidExtension())
        self.assertTrue('FOXNSOX' in ext_mgr.extensions)
        self.assertTrue('THIRD' not in ext_mgr.extensions)


class ActionExtensionTest(unittest.TestCase):

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def _send_server_action_request(self, url, body):
        app = openstack.APIRouterV11()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank(url)
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(ext_midware)
        return response

    def test_extended_action(self):
        body = dict(add_tweedle=dict(name="test"))
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Added.", response.body)

        body = dict(delete_tweedle=dict(name="test"))
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Deleted.", response.body)

    def test_invalid_action_body(self):
        body = dict(blah=dict(name="test"))  # Doesn't exist
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(501, response.status_int)

    def test_invalid_action(self):
        body = dict(blah=dict(name="test"))
        response = self._send_server_action_request("/asdf/1/action", body)
        self.assertEqual(404, response.status_int)


class RequestExtensionTest(unittest.TestCase):

    def setUp(self):
        super(RequestExtensionTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(RequestExtensionTest, self).tearDown()

    def test_get_resources_with_stub_mgr(self):

        def _req_handler(req, res):
            # only handle JSON responses
            data = json.loads(res.body)
            data['flavor']['googoose'] = req.GET.get('chewing')
            res.body = json.dumps(data)
            return res

        req_ext = extensions.RequestExtension('GET',
                                                '/v1.1/flavors/:(id)',
                                                _req_handler)

        manager = StubExtensionManager(None, None, req_ext)
        app = fakes.wsgi_app()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/v1.1/flavors/1?chewing=bluegoo")
        request.environ['api.version'] = '1.1'
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual('bluegoo', response_data['flavor']['googoose'])

    def test_get_resources_with_mgr(self):

        app = fakes.wsgi_app()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/v1.1/flavors/1?chewing=newblue")
        request.environ['api.version'] = '1.1'
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual('newblue', response_data['flavor']['googoose'])
        self.assertEqual("Pig Bands!", response_data['big_bands'])

class ExtensionsXMLSerializerTest(unittest.TestCase):
    def test_serialize(self):
        serializer = extensions.ExtensionsXMLSerializer()
        data = {
            'extension': {
                'name': 'ext1',
                "namespace" : "http://docs.rack.com/servers/api/ext/pie/v1.0",
                "alias" : "RS-PIE",
                "updated" : "2011-01-22T13:25:27-06:00",
                "description" : "Adds the capability to share an image.",
                "links" : [
                    {
                        "rel" : "describedby",
                        "type" : "application/pdf",
                        "href" : "http://docs.rack.com/servers/api/ext/cs.pdf"
                    },
                    {
                        "rel" : "describedby",
                        "type" : "application/vnd.sun.wadl+xml",
                        "href" : "http://docs.rack.com/servers/api/ext/cs.wadl"
                    }
                ]
            },
        }

        ns = "{http://docs.openstack.org/compute/api/v1.1}"
        atomns = "{http://www.w3.org/2005/Atom}"
        elem = ElementTree.XML(serializer.serialize(data, 'show'))
        self.assertEqual(elem.tag.split('extension')[0], ns)
        self.assertEqual(elem.get('alias'), 'RS-PIE')
        self.assertEqual(elem.get('name'), 'ext1')
        self.assertEqual(elem.get('namespace'),
            'http://docs.rack.com/servers/api/ext/pie/v1.0')
        self.assertEqual(elem.get('updated'), '2011-01-22T13:25:27-06:00')
        self.assertEqual(elem.findtext('{0}description'.format(ns)),
            'Adds the capability to share an image.')

        link_nodes = elem.findall('{0}link'.format(atomns))
        self.assertEqual(len(link_nodes), 2)
        link_nodes.sort(key=lambda x: x.get('type'))

        self.assertEqual(link_nodes[0].get('type'), 'application/pdf')
        self.assertEqual(link_nodes[0].get('rel'), 'describedby')
        self.assertEqual(link_nodes[0].get('href'), 
            'http://docs.rack.com/servers/api/ext/cs.pdf')

        self.assertEqual(link_nodes[1].get('type'), 
            'application/vnd.sun.wadl+xml')
        self.assertEqual(link_nodes[1].get('rel'), 'describedby')
        self.assertEqual(link_nodes[1].get('href'), 
            'http://docs.rack.com/servers/api/ext/cs.wadl')
