# Copyright (C) 2011 Midokura KK
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

import mock

import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import virtual_interfaces as vi21
from nova import compute
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import network
from nova.objects import virtual_interface as vif_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def compute_api_get(context, instance_id, expected_attrs=None):
    return dict(uuid=FAKE_UUID, id=instance_id, instance_type_id=1, host='bob')


def _generate_fake_vifs(context):
    vif = vif_obj.VirtualInterface(context=context)
    vif.address = '00-00-00-00-00-00'
    vif.network_id = 123
    vif.net_uuid = '22222222-2222-2222-2222-22222222222222222'
    vif.uuid = uuids.vif1_uuid
    fake_vifs = [vif]
    vif = vif_obj.VirtualInterface(context=context)
    vif.address = '11-11-11-11-11-11'
    vif.network_id = 456
    vif.net_uuid = '33333333-3333-3333-3333-33333333333333333'
    vif.uuid = uuids.vif2_uuid
    fake_vifs.append(vif)
    return fake_vifs


def get_vifs_by_instance(context, instance_id):
    return _generate_fake_vifs(context)


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class ServerVirtualInterfaceTestV21(test.NoDBTestCase):
    wsgi_api_version = '2.1'
    expected_response = {
        'virtual_interfaces': [
            {'id': uuids.vif1_uuid,
                'mac_address': '00-00-00-00-00-00'},
            {'id': uuids.vif2_uuid,
                'mac_address': '11-11-11-11-11-11'}]}

    def setUp(self):
        super(ServerVirtualInterfaceTestV21, self).setUp()
        # These APIs aren't implemented by the neutronv2 API code in Nova so
        # the tests need to specifically run against nova-network unless
        # otherwise setup to run with Neutron and expect failure.
        self.flags(use_neutron=False)
        self.compute_api_get_patcher = mock.patch.object(
            compute.api.API, "get",
            side_effect=compute_api_get)
        self.get_vifs_by_instance_patcher = mock.patch.object(
            network.api.API, "get_vifs_by_instance",
            side_effect=get_vifs_by_instance)
        self.compute_api_get_patcher.start()
        self.get_vifs_by_instance_patcher.start()
        self.addCleanup(self.compute_api_get_patcher.stop)
        self.addCleanup(self.get_vifs_by_instance_patcher.stop)
        self._set_controller()

    def _set_controller(self):
        self.controller = vi21.ServerVirtualInterfaceController()

    def test_get_virtual_interfaces_list(self):
        req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)
        res_dict = self.controller.index(req, 'fake_uuid')
        self.assertEqual(self.expected_response, res_dict)

    def test_get_virtual_interfaces_list_offset_and_limit(self):
        path = '/v2/fake/os-virtual-interfaces?offset=1&limit=1'
        req = fakes.HTTPRequest.blank(path, version=self.wsgi_api_version)
        res_dict = self.controller.index(req, 'fake_uuid')
        name = 'virtual_interfaces'
        limited_response = {name: [self.expected_response[name][1]]}
        self.assertEqual(limited_response, res_dict)

    @mock.patch.object(compute_api.API, 'get',
                       side_effect=exception.InstanceNotFound(
                           instance_id='instance-0000'))
    def test_vif_instance_not_found(self, mock_get):
        fake_context = context.RequestContext('fake', 'fake')
        fake_req = FakeRequest(fake_context)
        fake_req.api_version_request = api_version_request.APIVersionRequest(
                                        self.wsgi_api_version)
        self.assertRaises(
            webob.exc.HTTPNotFound,
            self.controller.index,
            fake_req, 'fake_uuid')
        mock_get.assert_called_once_with(fake_context,
                                         'fake_uuid',
                                         expected_attrs=None)

    def test_list_vifs_neutron_notimplemented(self):
        """Tests that a 400 is returned when using neutron as the backend"""
        # unset the get_vifs_by_instance stub from setUp
        self.get_vifs_by_instance_patcher.stop()
        self.flags(use_neutron=True)
        # reset the controller to use the neutron network API
        self._set_controller()
        req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req, FAKE_UUID)
        self.get_vifs_by_instance_patcher.start()


class ServerVirtualInterfaceTestV212(ServerVirtualInterfaceTestV21):
    wsgi_api_version = '2.12'

    expected_response = {
        'virtual_interfaces': [
            {'id': uuids.vif1_uuid,
                'mac_address': '00-00-00-00-00-00',
                'net_id': '22222222-2222-2222-2222-22222222222222222'},
            {'id': uuids.vif2_uuid,
                'mac_address': '11-11-11-11-11-11',
                'net_id': '33333333-3333-3333-3333-33333333333333333'}]}


class ServerVirtualInterfaceEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ServerVirtualInterfaceEnforcementV21, self).setUp()
        self.controller = vi21.ServerVirtualInterfaceController()
        self.req = fakes.HTTPRequest.blank('')

    def test_index_virtual_interfaces_policy_failed(self):
        rule_name = "os_compute_api:os-virtual-interfaces"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class ServerVirtualInterfaceDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(ServerVirtualInterfaceDeprecationTest, self).setUp()
        self.controller = vi21.ServerVirtualInterfaceController()
        self.req = fakes.HTTPRequest.blank('', version='2.44')

    def test_index_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req, FAKE_UUID)
