# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

import webob
from lxml import etree

from nova.api.openstack import v2
from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import wsgi as base_wsgi

FLAGS = flags.FLAGS

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
response_body = "Try to say this Mr. Knox, sir..."


class StubController(object):

    def __init__(self, body):
        self.body = body

    def index(self, req):
        return self.body

    def create(self, req):
        msg = 'All aboard the fail train!'
        raise webob.exc.HTTPBadRequest(explanation=msg)

    def show(self, req, id):
        raise webob.exc.HTTPNotFound()


class StubExtensionManager(object):
    """Provides access to Tweedle Beetles"""

    name = "Tweedle Beetle Extension"
    alias = "TWDLBETL"

    def __init__(self, resource_ext=None, action_ext=None, request_ext=None):
        self.resource_ext = resource_ext
        self.action_ext = action_ext
        self.request_ext = request_ext

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


class ExtensionTestCase(test.TestCase):
    def setUp(self):
        super(ExtensionTestCase, self).setUp()
        ext_list = FLAGS.osapi_extension[:]
        ext_list.append('nova.tests.api.openstack.v2.extensions.'
                        'foxinsocks.Foxinsocks')
        self.flags(osapi_extension=ext_list)
        extensions.ExtensionManager.reset()


class ExtensionControllerTest(ExtensionTestCase):

    def setUp(self):
        super(ExtensionControllerTest, self).setUp()
        self.flags(allow_admin_api=True)
        self.ext_list = [
            "Accounts",
            "AdminActions",
            "Cloudpipe",
            "Console_output",
            "Createserverext",
            "DeferredDelete",
            "DiskConfig",
            "ExtendedStatus",
            "FlavorExtraSpecs",
            "FlavorExtraData",
            "Floating_ips",
            "Floating_ip_dns",
            "Floating_ip_pools",
            "Fox In Socks",
            "Hosts",
            "Keypairs",
            "Multinic",
            "Quotas",
            "Rescue",
            "SecurityGroups",
            "ServerActionList",
            "ServerDiagnostics",
            "SimpleTenantUsage",
            "Users",
            "VSAs",
            "VirtualInterfaces",
            "Volumes",
            "VolumeTypes",
            "Zones",
            "Networks",
            ]
        self.ext_list.sort()

    def test_list_extensions_json(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/extensions")
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)

        # Make sure we have all the extensions.
        data = json.loads(response.body)
        names = [x['name'] for x in data['extensions']]
        names.sort()
        self.assertEqual(names, self.ext_list)

        # Make sure that at least Fox in Sox is correct.
        (fox_ext, ) = [
            x for x in data['extensions'] if x['alias'] == 'FOXNSOX']
        self.assertEqual(fox_ext, {
                'namespace': 'http://www.fox.in.socks/api/ext/pie/v1.0',
                'name': 'Fox In Socks',
                'updated': '2011-01-22T13:25:27-06:00',
                'description': 'The Fox In Socks Extension',
                'alias': 'FOXNSOX',
                'links': []
            },
        )

    def test_get_extension_json(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/extensions/FOXNSOX")
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)

        data = json.loads(response.body)
        self.assertEqual(data['extension'], {
                "namespace": "http://www.fox.in.socks/api/ext/pie/v1.0",
                "name": "Fox In Socks",
                "updated": "2011-01-22T13:25:27-06:00",
                "description": "The Fox In Socks Extension",
                "alias": "FOXNSOX",
                "links": []})

    def test_get_non_existing_extension_json(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/fake/extensions/4")
        response = request.get_response(ext_midware)
        self.assertEqual(404, response.status_int)

    def test_list_extensions_xml(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/extensions")
        request.accept = "application/xml"
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        print response.body

        root = etree.XML(response.body)
        self.assertEqual(root.tag.split('extensions')[0], NS)

        # Make sure we have all the extensions.
        exts = root.findall('{0}extension'.format(NS))
        self.assertEqual(len(exts), len(self.ext_list))

        # Make sure that at least Fox in Sox is correct.
        (fox_ext, ) = [x for x in exts if x.get('alias') == 'FOXNSOX']
        self.assertEqual(fox_ext.get('name'), 'Fox In Socks')
        self.assertEqual(fox_ext.get('namespace'),
            'http://www.fox.in.socks/api/ext/pie/v1.0')
        self.assertEqual(fox_ext.get('updated'), '2011-01-22T13:25:27-06:00')
        self.assertEqual(fox_ext.findtext('{0}description'.format(NS)),
            'The Fox In Socks Extension')

        xmlutil.validate_schema(root, 'extensions')

    def test_get_extension_xml(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/extensions/FOXNSOX")
        request.accept = "application/xml"
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        xml = response.body
        print xml

        root = etree.XML(xml)
        self.assertEqual(root.tag.split('extension')[0], NS)
        self.assertEqual(root.get('alias'), 'FOXNSOX')
        self.assertEqual(root.get('name'), 'Fox In Socks')
        self.assertEqual(root.get('namespace'),
            'http://www.fox.in.socks/api/ext/pie/v1.0')
        self.assertEqual(root.get('updated'), '2011-01-22T13:25:27-06:00')
        self.assertEqual(root.findtext('{0}description'.format(NS)),
            'The Fox In Socks Extension')

        xmlutil.validate_schema(root, 'extension')


class ResourceExtensionTest(ExtensionTestCase):

    def test_no_extension_present(self):
        manager = StubExtensionManager(None)
        app = v2.APIRouter(manager)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/blah")
        response = request.get_response(ser_midware)
        self.assertEqual(404, response.status_int)

    def test_get_resources(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = v2.APIRouter(manager)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_get_resources_with_controller(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = v2.APIRouter(manager)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_bad_request(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = v2.APIRouter(manager)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/tweedles")
        request.method = "POST"
        response = request.get_response(ser_midware)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        body = json.loads(response.body)
        expected = {
            "badRequest": {
                "message": "All aboard the fail train!",
                "code": 400
            }
        }
        self.assertDictMatch(expected, body)

    def test_non_exist_resource(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = v2.APIRouter(manager)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/tweedles/1")
        response = request.get_response(ser_midware)
        self.assertEqual(404, response.status_int)
        self.assertEqual('application/json', response.content_type)
        body = json.loads(response.body)
        expected = {
            "itemNotFound": {
                "message": "The resource could not be found.",
                "code": 404
            }
        }
        self.assertDictMatch(expected, body)


class InvalidExtension(object):

    alias = "THIRD"


class AdminExtension(extensions.ExtensionDescriptor):
    """Admin-only extension"""

    name = "Admin Ext"
    alias = "ADMIN"
    namespace = "http://www.example.com/"
    updated = "2011-01-22T13:25:27-06:00"
    admin_only = True

    def __init__(self, *args, **kwargs):
        pass


class ExtensionManagerTest(ExtensionTestCase):

    response_body = "Try to say this Mr. Knox, sir..."

    def test_get_resources(self):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/fake/foxnsocks")
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_invalid_extensions(self):
        # Don't need the serialization middleware here because we're
        # not testing any serialization
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ext_mgr = ext_midware.ext_mgr
        ext_mgr.register(InvalidExtension())
        self.assertTrue('FOXNSOX' in ext_mgr.extensions)
        self.assertTrue('THIRD' not in ext_mgr.extensions)

    def test_admin_extensions(self):
        self.flags(allow_admin_api=True)
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ext_mgr = ext_midware.ext_mgr
        ext_mgr.register(AdminExtension())
        self.assertTrue('FOXNSOX' in ext_mgr.extensions)
        self.assertTrue('ADMIN' in ext_mgr.extensions)

    def test_admin_extensions_no_admin_api(self):
        self.flags(allow_admin_api=False)
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ext_mgr = ext_midware.ext_mgr
        ext_mgr.register(AdminExtension())
        self.assertTrue('FOXNSOX' in ext_mgr.extensions)
        self.assertTrue('ADMIN' not in ext_mgr.extensions)


class ActionExtensionTest(ExtensionTestCase):

    def _send_server_action_request(self, url, body):
        app = v2.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank(url)
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(ser_midware)
        return response

    def test_extended_action(self):
        body = dict(add_tweedle=dict(name="test"))
        url = "/fake/servers/abcd/action"
        response = self._send_server_action_request(url, body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Added.", response.body)

        body = dict(delete_tweedle=dict(name="test"))
        response = self._send_server_action_request(url, body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Deleted.", response.body)

    def test_invalid_action(self):
        body = dict(blah=dict(name="test"))  # Doesn't exist
        url = "/fake/servers/abcd/action"
        response = self._send_server_action_request(url, body)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        body = json.loads(response.body)
        expected = {
            "badRequest": {
                "message": "There is no such server action: blah",
                "code": 400
            }
        }
        self.assertDictMatch(expected, body)

    def test_non_exist_action(self):
        body = dict(blah=dict(name="test"))
        url = "/fake/fdsa/1/action"
        response = self._send_server_action_request(url, body)
        self.assertEqual(404, response.status_int)

    def test_failed_action(self):
        body = dict(fail=dict(name="test"))
        url = "/fake/servers/abcd/action"
        response = self._send_server_action_request(url, body)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        body = json.loads(response.body)
        expected = {
            "badRequest": {
                "message": "Tweedle fail",
                "code": 400
            }
        }
        self.assertDictMatch(expected, body)


class RequestExtensionTest(ExtensionTestCase):

    def test_get_resources_with_stub_mgr(self):

        def _req_handler(req, res, body):
            # only handle JSON responses
            body['flavor']['googoose'] = req.GET.get('chewing')
            return res

        req_ext = extensions.RequestExtension('GET',
                                                '/v2/fake/flavors/:(id)',
                                                _req_handler)

        manager = StubExtensionManager(None, None, req_ext)
        app = fakes.wsgi_app(serialization=base_wsgi.Middleware)
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/v2/fake/flavors/1?chewing=bluegoo")
        request.environ['api.version'] = '2'
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual('bluegoo', response_data['flavor']['googoose'])

    def test_get_resources_with_mgr(self):

        app = fakes.wsgi_app(serialization=base_wsgi.Middleware)
        ext_midware = extensions.ExtensionMiddleware(app)
        ser_midware = wsgi.LazySerializationMiddleware(ext_midware)
        request = webob.Request.blank("/v2/fake/flavors/1?chewing=newblue")
        request.environ['api.version'] = '2'
        response = request.get_response(ser_midware)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        print response_data
        self.assertEqual('newblue', response_data['flavor']['googoose'])
        self.assertEqual("Pig Bands!", response_data['big_bands'])


class ExtensionsXMLSerializerTest(test.TestCase):

    def test_serialize_extension(self):
        serializer = extensions.ExtensionsXMLSerializer()
        data = {'extension': {
          'name': 'ext1',
          'namespace': 'http://docs.rack.com/servers/api/ext/pie/v1.0',
          'alias': 'RS-PIE',
          'updated': '2011-01-22T13:25:27-06:00',
          'description': 'Adds the capability to share an image.',
          'links': [{'rel': 'describedby',
                     'type': 'application/pdf',
                     'href': 'http://docs.rack.com/servers/api/ext/cs.pdf'},
                    {'rel': 'describedby',
                     'type': 'application/vnd.sun.wadl+xml',
                     'href': 'http://docs.rack.com/servers/api/ext/cs.wadl'}]}}

        xml = serializer.serialize(data, 'show')
        print xml
        root = etree.XML(xml)
        ext_dict = data['extension']
        self.assertEqual(root.findtext('{0}description'.format(NS)),
            ext_dict['description'])

        for key in ['name', 'namespace', 'alias', 'updated']:
            self.assertEqual(root.get(key), ext_dict[key])

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(ext_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        xmlutil.validate_schema(root, 'extension')

    def test_serialize_extensions(self):
        serializer = extensions.ExtensionsXMLSerializer()
        data = {"extensions": [{
                "name": "Public Image Extension",
                "namespace": "http://foo.com/api/ext/pie/v1.0",
                "alias": "RS-PIE",
                "updated": "2011-01-22T13:25:27-06:00",
                "description": "Adds the capability to share an image.",
                "links": [{"rel": "describedby",
                            "type": "application/pdf",
                            "type": "application/vnd.sun.wadl+xml",
                            "href": "http://foo.com/api/ext/cs-pie.pdf"},
                           {"rel": "describedby",
                            "type": "application/vnd.sun.wadl+xml",
                            "href": "http://foo.com/api/ext/cs-pie.wadl"}]},
                {"name": "Cloud Block Storage",
                 "namespace": "http://foo.com/api/ext/cbs/v1.0",
                 "alias": "RS-CBS",
                 "updated": "2011-01-12T11:22:33-06:00",
                 "description": "Allows mounting cloud block storage.",
                 "links": [{"rel": "describedby",
                             "type": "application/pdf",
                             "href": "http://foo.com/api/ext/cs-cbs.pdf"},
                            {"rel": "describedby",
                             "type": "application/vnd.sun.wadl+xml",
                             "href": "http://foo.com/api/ext/cs-cbs.wadl"}]}]}

        xml = serializer.serialize(data, 'index')
        print xml
        root = etree.XML(xml)
        ext_elems = root.findall('{0}extension'.format(NS))
        self.assertEqual(len(ext_elems), 2)
        for i, ext_elem in enumerate(ext_elems):
            ext_dict = data['extensions'][i]
            self.assertEqual(ext_elem.findtext('{0}description'.format(NS)),
                ext_dict['description'])

            for key in ['name', 'namespace', 'alias', 'updated']:
                self.assertEqual(ext_elem.get(key), ext_dict[key])

            link_nodes = ext_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(ext_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

        xmlutil.validate_schema(root, 'extensions')
