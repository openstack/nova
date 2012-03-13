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

from nova.api.openstack import compute
from nova.api.openstack import extensions as base_extensions
from nova.api.openstack.compute import extensions as compute_extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS

NS = "{http://docs.openstack.org/common/api/v1.0}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
response_body = "Try to say this Mr. Knox, sir..."
extension_body = "I am not a fox!"


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


class StubActionController(wsgi.Controller):
    def __init__(self, body):
        self.body = body

    @wsgi.action('fooAction')
    def _action_foo(self, req, id, body):
        return self.body


class StubControllerExtension(base_extensions.ExtensionDescriptor):
    name = 'twaadle'

    def __init__(self):
        pass


class StubEarlyExtensionController(wsgi.Controller):
    def __init__(self, body):
        self.body = body

    @wsgi.extends
    def index(self, req):
        yield self.body

    @wsgi.extends(action='fooAction')
    def _action_foo(self, req, id, body):
        yield self.body


class StubLateExtensionController(wsgi.Controller):
    def __init__(self, body):
        self.body = body

    @wsgi.extends
    def index(self, req, resp_obj):
        return self.body

    @wsgi.extends(action='fooAction')
    def _action_foo(self, req, resp_obj, id, body):
        return self.body


class StubExtensionManager(object):
    """Provides access to Tweedle Beetles"""

    name = "Tweedle Beetle Extension"
    alias = "TWDLBETL"

    def __init__(self, resource_ext=None, action_ext=None, request_ext=None,
                 controller_ext=None):
        self.resource_ext = resource_ext
        self.action_ext = action_ext
        self.request_ext = request_ext
        self.controller_ext = controller_ext

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

    def get_controller_extensions(self):
        controller_extensions = []
        if self.controller_ext:
            controller_extensions.append(self.controller_ext)
        return controller_extensions


class ExtensionTestCase(test.TestCase):
    def setUp(self):
        super(ExtensionTestCase, self).setUp()
        ext_list = FLAGS.osapi_compute_extension[:]
        fox = ('nova.tests.api.openstack.compute.extensions.'
               'foxinsocks.Foxinsocks')
        if fox not in ext_list:
            ext_list.append(fox)
            self.flags(osapi_compute_extension=ext_list)


class ExtensionControllerTest(ExtensionTestCase):

    def setUp(self):
        super(ExtensionControllerTest, self).setUp()
        self.ext_list = [
            "Accounts",
            "AdminActions",
            "Aggregates",
            "Certificates",
            "Cloudpipe",
            "Console_output",
            "Consoles",
            "Createserverext",
            "DeferredDelete",
            "DiskConfig",
            "ExtendedStatus",
            "ExtendedServerAttributes",
            "FlavorExtraSpecs",
            "FlavorExtraData",
            "FlavorManage",
            "Floating_ips",
            "Floating_ip_dns",
            "Floating_ip_pools",
            "Fox In Socks",
            "Hosts",
            "Keypairs",
            "Multinic",
            "Networks",
            "QuotaClasses",
            "Quotas",
            "Rescue",
            "SchedulerHints",
            "SecurityGroups",
            "ServerActionList",
            "ServerDiagnostics",
            "ServerStartStop",
            "SimpleTenantUsage",
            "Users",
            "VirtualInterfaces",
            "Volumes",
            "VolumeTypes",
            ]
        self.ext_list.sort()

    def test_list_extensions_json(self):
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/extensions")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)

        # Make sure we have all the extensions, extra extensions being OK.
        data = json.loads(response.body)
        names = [str(x['name']) for x in data['extensions']
                 if str(x['name']) in self.ext_list]
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

        for ext in data['extensions']:
            url = '/fake/extensions/%s' % ext['alias']
            request = webob.Request.blank(url)
            response = request.get_response(app)
            output = json.loads(response.body)
            self.assertEqual(output['extension']['alias'], ext['alias'])

    def test_get_extension_json(self):
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/extensions/FOXNSOX")
        response = request.get_response(app)
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
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/extensions/4")
        response = request.get_response(app)
        self.assertEqual(404, response.status_int)

    def test_list_extensions_xml(self):
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/extensions")
        request.accept = "application/xml"
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)

        root = etree.XML(response.body)
        self.assertEqual(root.tag.split('extensions')[0], NS)

        # Make sure we have all the extensions, extras extensions being OK.
        exts = root.findall('{0}extension'.format(NS))
        self.assert_(len(exts) >= len(self.ext_list))

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
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/extensions/FOXNSOX")
        request.accept = "application/xml"
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        xml = response.body

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
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/blah")
        response = request.get_response(app)
        self.assertEqual(404, response.status_int)

    def test_get_resources(self):
        res_ext = base_extensions.ResourceExtension('tweedles',
                                  StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_get_resources_with_controller(self):
        res_ext = base_extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_bad_request(self):
        res_ext = base_extensions.ResourceExtension('tweedles',
                                  StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles")
        request.method = "POST"
        response = request.get_response(app)
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
        res_ext = base_extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles/1")
        response = request.get_response(app)
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


class ExtensionManagerTest(ExtensionTestCase):

    response_body = "Try to say this Mr. Knox, sir..."

    def test_get_resources(self):
        app = compute.APIRouter()
        request = webob.Request.blank("/fake/foxnsocks")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_invalid_extensions(self):
        # Don't need the serialization middleware here because we're
        # not testing any serialization
        app = compute.APIRouter()
        ext_mgr = compute_extensions.ExtensionManager()
        ext_mgr.register(InvalidExtension())
        self.assertTrue('FOXNSOX' in ext_mgr.extensions)
        self.assertTrue('THIRD' not in ext_mgr.extensions)


class ActionExtensionTest(ExtensionTestCase):

    def _send_server_action_request(self, url, body):
        app = compute.APIRouter()
        request = webob.Request.blank(url)
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(app)
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
                "message": "There is no such action: blah",
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
        class GooGoose(wsgi.Controller):
            @wsgi.extends
            def show(self, req, resp_obj, id):
                # only handle JSON responses
                resp_obj.obj['flavor']['googoose'] = req.GET.get('chewing')

        req_ext = base_extensions.ControllerExtension(
            StubControllerExtension(), 'flavors', GooGoose())

        manager = StubExtensionManager(None, None, None, req_ext)
        app = fakes.wsgi_app(ext_mgr=manager)
        request = webob.Request.blank("/v2/fake/flavors/1?chewing=bluegoo")
        request.environ['api.version'] = '2'
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual('bluegoo', response_data['flavor']['googoose'])

    def test_get_resources_with_mgr(self):

        app = fakes.wsgi_app()
        request = webob.Request.blank("/v2/fake/flavors/1?chewing=newblue")
        request.environ['api.version'] = '2'
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual('newblue', response_data['flavor']['googoose'])
        self.assertEqual("Pig Bands!", response_data['big_bands'])


class ControllerExtensionTest(ExtensionTestCase):
    def test_controller_extension_early(self):
        controller = StubController(response_body)
        res_ext = base_extensions.ResourceExtension('tweedles', controller)
        ext_controller = StubEarlyExtensionController(extension_body)
        extension = StubControllerExtension()
        cont_ext = base_extensions.ControllerExtension(extension, 'tweedles',
                                                       ext_controller)
        manager = StubExtensionManager(resource_ext=res_ext,
                                       controller_ext=cont_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(extension_body, response.body)

    def test_controller_extension_late(self):
        # Need a dict for the body to convert to a ResponseObject
        controller = StubController(dict(foo=response_body))
        res_ext = base_extensions.ResourceExtension('tweedles', controller)

        ext_controller = StubLateExtensionController(extension_body)
        extension = StubControllerExtension()
        cont_ext = base_extensions.ControllerExtension(extension, 'tweedles',
                                                       ext_controller)

        manager = StubExtensionManager(resource_ext=res_ext,
                                       controller_ext=cont_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(extension_body, response.body)

    def test_controller_action_extension_early(self):
        controller = StubActionController(response_body)
        actions = dict(action='POST')
        res_ext = base_extensions.ResourceExtension('tweedles', controller,
                                                    member_actions=actions)
        ext_controller = StubEarlyExtensionController(extension_body)
        extension = StubControllerExtension()
        cont_ext = base_extensions.ControllerExtension(extension, 'tweedles',
                                                       ext_controller)
        manager = StubExtensionManager(resource_ext=res_ext,
                                       controller_ext=cont_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles/foo/action")
        request.method = 'POST'
        request.headers['Content-Type'] = 'application/json'
        request.body = json.dumps(dict(fooAction=True))
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(extension_body, response.body)

    def test_controller_action_extension_late(self):
        # Need a dict for the body to convert to a ResponseObject
        controller = StubActionController(dict(foo=response_body))
        actions = dict(action='POST')
        res_ext = base_extensions.ResourceExtension('tweedles', controller,
                                                    member_actions=actions)

        ext_controller = StubLateExtensionController(extension_body)
        extension = StubControllerExtension()
        cont_ext = base_extensions.ControllerExtension(extension, 'tweedles',
                                                       ext_controller)

        manager = StubExtensionManager(resource_ext=res_ext,
                                       controller_ext=cont_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles/foo/action")
        request.method = 'POST'
        request.headers['Content-Type'] = 'application/json'
        request.body = json.dumps(dict(fooAction=True))
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(extension_body, response.body)


class ExtensionsXMLSerializerTest(test.TestCase):

    def test_serialize_extension(self):
        serializer = base_extensions.ExtensionTemplate()
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

        xml = serializer.serialize(data)
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
        serializer = base_extensions.ExtensionsTemplate()
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

        xml = serializer.serialize(data)
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
