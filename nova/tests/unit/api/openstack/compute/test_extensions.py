# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2011 OpenStack Foundation
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

import iso8601
from oslo.config import cfg
from oslo.serialization import jsonutils
import webob

from nova.api.openstack import compute
from nova.api.openstack.compute import extensions as compute_extensions
from nova.api.openstack import extensions as base_extensions
from nova.api.openstack import wsgi
from nova import exception
import nova.policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers

CONF = cfg.CONF

NS = "{http://docs.openstack.org/common/api/v1.0}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
response_body = "Try to say this Mr. Knox, sir..."
extension_body = "I am not a fox!"


class StubController(object):

    def __init__(self, body):
        self.body = body

    def index(self, req):
        return self.body

    def create(self, req, body):
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
    """Provides access to Tweedle Beetles."""

    name = "Tweedle Beetle Extension"
    alias = "TWDLBETL"

    def __init__(self, resource_ext=None, action_ext=None, request_ext=None,
                 controller_ext=None):
        self.resource_ext = resource_ext
        self.action_ext = action_ext
        self.request_ext = request_ext
        self.controller_ext = controller_ext
        self.extra_resource_ext = None

    def get_resources(self):
        resource_exts = []
        if self.resource_ext:
            resource_exts.append(self.resource_ext)
        if self.extra_resource_ext:
            resource_exts.append(self.extra_resource_ext)
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
        ext_list = CONF.osapi_compute_extension[:]
        fox = ('nova.tests.unit.api.openstack.compute.extensions.'
               'foxinsocks.Foxinsocks')
        if fox not in ext_list:
            ext_list.append(fox)
            self.flags(osapi_compute_extension=ext_list)
        self.fake_context = nova.context.RequestContext('fake', 'fake')

    def test_extension_authorizer_throws_exception_if_policy_fails(self):
        target = {'project_id': '1234',
                  'user_id': '5678'}
        self.mox.StubOutWithMock(nova.policy, 'enforce')
        nova.policy.enforce(self.fake_context,
                            "compute_extension:used_limits_for_admin",
                            target).AndRaise(
            exception.PolicyNotAuthorized(
                action="compute_extension:used_limits_for_admin"))
        self.mox.ReplayAll()
        authorize = base_extensions.extension_authorizer('compute',
                                                        'used_limits_for_admin'
        )
        self.assertRaises(exception.PolicyNotAuthorized, authorize,
                          self.fake_context, target=target)

    def test_core_authorizer_throws_exception_if_policy_fails(self):
        target = {'project_id': '1234',
                  'user_id': '5678'}
        self.mox.StubOutWithMock(nova.policy, 'enforce')
        nova.policy.enforce(self.fake_context,
                            "compute:used_limits_for_admin",
                            target).AndRaise(
            exception.PolicyNotAuthorized(
                action="compute:used_limits_for_admin"))
        self.mox.ReplayAll()
        authorize = base_extensions.core_authorizer('compute',
                                                    'used_limits_for_admin'
        )
        self.assertRaises(exception.PolicyNotAuthorized, authorize,
                          self.fake_context, target=target)


class ExtensionControllerTest(ExtensionTestCase):

    def setUp(self):
        super(ExtensionControllerTest, self).setUp()
        self.ext_list = [
            "AdminActions",
            "Aggregates",
            "AssistedVolumeSnapshots",
            "AvailabilityZone",
            "Agents",
            "Certificates",
            "Cloudpipe",
            "CloudpipeUpdate",
            "ConsoleOutput",
            "Consoles",
            "Createserverext",
            "DeferredDelete",
            "DiskConfig",
            "ExtendedAvailabilityZone",
            "ExtendedFloatingIps",
            "ExtendedIps",
            "ExtendedIpsMac",
            "ExtendedVIFNet",
            "Evacuate",
            "ExtendedStatus",
            "ExtendedVolumes",
            "ExtendedServerAttributes",
            "FixedIPs",
            "FlavorAccess",
            "FlavorDisabled",
            "FlavorExtraSpecs",
            "FlavorExtraData",
            "FlavorManage",
            "FlavorRxtx",
            "FlavorSwap",
            "FloatingIps",
            "FloatingIpDns",
            "FloatingIpPools",
            "FloatingIpsBulk",
            "Fox In Socks",
            "Hosts",
            "ImageSize",
            "InstanceActions",
            "Keypairs",
            "Multinic",
            "MultipleCreate",
            "QuotaClasses",
            "Quotas",
            "ExtendedQuotas",
            "Rescue",
            "SchedulerHints",
            "SecurityGroupDefaultRules",
            "SecurityGroups",
            "ServerDiagnostics",
            "ServerListMultiStatus",
            "ServerPassword",
            "ServerStartStop",
            "Services",
            "SimpleTenantUsage",
            "UsedLimits",
            "UserData",
            "VirtualInterfaces",
            "VolumeAttachmentUpdate",
            "Volumes",
            ]
        self.ext_list.sort()

    def test_list_extensions_json(self):
        app = compute.APIRouter(init_only=('extensions',))
        request = webob.Request.blank("/fake/extensions")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)

        # Make sure we have all the extensions, extra extensions being OK.
        data = jsonutils.loads(response.body)
        names = [str(x['name']) for x in data['extensions']
                 if str(x['name']) in self.ext_list]
        names.sort()
        self.assertEqual(names, self.ext_list)

        # Ensure all the timestamps are valid according to iso8601
        for ext in data['extensions']:
            iso8601.parse_date(ext['updated'])

        # Make sure that at least Fox in Sox is correct.
        (fox_ext, ) = [
            x for x in data['extensions'] if x['alias'] == 'FOXNSOX']
        self.assertEqual(fox_ext, {
                'namespace': 'http://www.fox.in.socks/api/ext/pie/v1.0',
                'name': 'Fox In Socks',
                'updated': '2011-01-22T13:25:27-06:00',
                'description': 'The Fox In Socks Extension.',
                'alias': 'FOXNSOX',
                'links': []
            },
        )

        for ext in data['extensions']:
            url = '/fake/extensions/%s' % ext['alias']
            request = webob.Request.blank(url)
            response = request.get_response(app)
            output = jsonutils.loads(response.body)
            self.assertEqual(output['extension']['alias'], ext['alias'])

    def test_get_extension_json(self):
        app = compute.APIRouter(init_only=('extensions',))
        request = webob.Request.blank("/fake/extensions/FOXNSOX")
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)

        data = jsonutils.loads(response.body)
        self.assertEqual(data['extension'], {
                "namespace": "http://www.fox.in.socks/api/ext/pie/v1.0",
                "name": "Fox In Socks",
                "updated": "2011-01-22T13:25:27-06:00",
                "description": "The Fox In Socks Extension.",
                "alias": "FOXNSOX",
                "links": []})

    def test_get_non_existing_extension_json(self):
        app = compute.APIRouter(init_only=('extensions',))
        request = webob.Request.blank("/fake/extensions/4")
        response = request.get_response(app)
        self.assertEqual(404, response.status_int)


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
        body = jsonutils.loads(response.body)
        expected = {
            "badRequest": {
                "message": "All aboard the fail train!",
                "code": 400
            }
        }
        self.assertThat(expected, matchers.DictMatches(body))

    def test_non_exist_resource(self):
        res_ext = base_extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/tweedles/1")
        response = request.get_response(app)
        self.assertEqual(404, response.status_int)
        self.assertEqual('application/json', response.content_type)
        body = jsonutils.loads(response.body)
        expected = {
            "itemNotFound": {
                "message": "The resource could not be found.",
                "code": 404
            }
        }
        self.assertThat(expected, matchers.DictMatches(body))


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
        compute.APIRouter()
        ext_mgr = compute_extensions.ExtensionManager()
        ext_mgr.register(InvalidExtension())
        self.assertTrue(ext_mgr.is_loaded('FOXNSOX'))
        self.assertFalse(ext_mgr.is_loaded('THIRD'))


class ActionExtensionTest(ExtensionTestCase):

    def _send_server_action_request(self, url, body):
        app = compute.APIRouter(init_only=('servers',))
        request = webob.Request.blank(url)
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = jsonutils.dumps(body)
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
        body = jsonutils.loads(response.body)
        expected = {
            "badRequest": {
                "message": "There is no such action: blah",
                "code": 400
            }
        }
        self.assertThat(expected, matchers.DictMatches(body))

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
        body = jsonutils.loads(response.body)
        expected = {
            "badRequest": {
                "message": "Tweedle fail",
                "code": 400
            }
        }
        self.assertThat(expected, matchers.DictMatches(body))


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
        response_data = jsonutils.loads(response.body)
        self.assertEqual('bluegoo', response_data['flavor']['googoose'])

    def test_get_resources_with_mgr(self):

        app = fakes.wsgi_app(init_only=('flavors',))
        request = webob.Request.blank("/v2/fake/flavors/1?chewing=newblue")
        request.environ['api.version'] = '2'
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        response_data = jsonutils.loads(response.body)
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

    def test_controller_extension_late_inherited_resource(self):
        # Need a dict for the body to convert to a ResponseObject
        controller = StubController(dict(foo=response_body))
        parent_ext = base_extensions.ResourceExtension('tweedles', controller)

        ext_controller = StubLateExtensionController(extension_body)
        extension = StubControllerExtension()
        cont_ext = base_extensions.ControllerExtension(extension, 'tweedles',
                                                       ext_controller)

        manager = StubExtensionManager(resource_ext=parent_ext,
                                       controller_ext=cont_ext)
        child_ext = base_extensions.ResourceExtension('beetles', controller,
                                                      inherits='tweedles')
        manager.extra_resource_ext = child_ext
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/beetles")
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
        request.body = jsonutils.dumps(dict(fooAction=True))
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
        request.body = jsonutils.dumps(dict(fooAction=True))
        response = request.get_response(app)
        self.assertEqual(200, response.status_int)
        self.assertEqual(extension_body, response.body)


class ExtensionControllerIdFormatTest(test.TestCase):

    def _bounce_id(self, test_id):

        class BounceController(object):
            def show(self, req, id):
                return id
        res_ext = base_extensions.ResourceExtension('bounce',
                                                    BounceController())
        manager = StubExtensionManager(res_ext)
        app = compute.APIRouter(manager)
        request = webob.Request.blank("/fake/bounce/%s" % test_id)
        response = request.get_response(app)
        return response.body

    def test_id_with_xml_format(self):
        result = self._bounce_id('foo.xml')
        self.assertEqual(result, 'foo')

    def test_id_with_json_format(self):
        result = self._bounce_id('foo.json')
        self.assertEqual(result, 'foo')

    def test_id_with_bad_format(self):
        result = self._bounce_id('foo.bad')
        self.assertEqual(result, 'foo.bad')
