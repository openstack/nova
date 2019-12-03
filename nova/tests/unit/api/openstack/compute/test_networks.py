# Copyright 2011 Grid Dynamics
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

import copy

from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import networks as networks_v21
from nova import exception
from nova.network import neutron
from nova import test
from nova.tests.unit.api.openstack import fakes


# NOTE(stephenfin): obviously these aren't complete reponses, but this is all
# we care about
FAKE_NETWORKS = [
    {
        'id': uuids.private,
        'name': 'private',
    },
    {
        'id': uuids.public,
        'name': 'public',
    },
]

USER_RESPONSE_TEMPLATE = {
    field: None for field in (
        'id', 'cidr', 'netmask', 'gateway', 'broadcast', 'dns1', 'dns2',
        'cidr_v6', 'gateway_v6', 'label', 'netmask_v6')
}

ADMIN_RESPONSE_TEMPLATE = {
    field: None for field in (
        'id', 'cidr', 'netmask', 'gateway', 'broadcast', 'dns1', 'dns2',
        'cidr_v6', 'gateway_v6', 'label', 'netmask_v6', 'created_at',
        'updated_at', 'deleted_at', 'deleted', 'injected', 'bridge', 'vlan',
        'vpn_public_address', 'vpn_public_port', 'vpn_private_address',
        'dhcp_start', 'project_id', 'host', 'bridge_interface', 'multi_host',
        'priority', 'rxtx_base', 'mtu', 'dhcp_server', 'enable_dhcp',
        'share_address')
}


class FakeNetworkAPI(object):

    def __init__(self):
        self.networks = copy.deepcopy(FAKE_NETWORKS)

    def get_all(self, context):
        return self.networks

    def get(self, context, network_id):
        for network in self.networks:
            if network['id'] == network_id:
                return network
        raise exception.NetworkNotFound(network_id=network_id)


class NetworksTestV21(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(NetworksTestV21, self).setUp()
        # TODO(stephenfin): Consider using then NeutronFixture here
        self.fake_network_api = FakeNetworkAPI()
        self._setup()
        fakes.stub_out_networking(self)
        self.non_admin_req = fakes.HTTPRequest.blank(
            '', project_id=fakes.FAKE_PROJECT_ID)
        self.admin_req = fakes.HTTPRequest.blank(
            '', project_id=fakes.FAKE_PROJECT_ID, use_admin_context=True)

    def _setup(self):
        self.controller = networks_v21.NetworkController(
            self.fake_network_api)
        self.neutron_ctrl = networks_v21.NetworkController(
            neutron.API())
        self.req = fakes.HTTPRequest.blank('',
                                           project_id=fakes.FAKE_PROJECT_ID)

    def _check_status(self, res, method, code):
        self.assertEqual(method.wsgi_code, code)

    def test_network_list_all_as_user(self):
        res_dict = self.controller.index(self.non_admin_req)

        expected = []
        for fake_network in FAKE_NETWORKS:
            expected_ = copy.deepcopy(USER_RESPONSE_TEMPLATE)
            expected_['id'] = fake_network['id']
            expected_['label'] = fake_network['name']
            expected.append(expected_)

        self.assertEqual({'networks': expected}, res_dict)

    def test_network_list_all_as_admin(self):
        res_dict = self.controller.index(self.admin_req)

        expected = []
        for fake_network in FAKE_NETWORKS:
            expected_ = copy.deepcopy(ADMIN_RESPONSE_TEMPLATE)
            expected_['id'] = fake_network['id']
            expected_['label'] = fake_network['name']
            expected.append(expected_)

        self.assertEqual({'networks': expected}, res_dict)

    def test_network_get_as_user(self):
        uuid = FAKE_NETWORKS[0]['id']
        res_dict = self.controller.show(self.non_admin_req, uuid)

        expected = copy.deepcopy(USER_RESPONSE_TEMPLATE)
        expected['id'] = FAKE_NETWORKS[0]['id']
        expected['label'] = FAKE_NETWORKS[0]['name']

        self.assertEqual({'network': expected}, res_dict)

    def test_network_get_as_admin(self):
        uuid = FAKE_NETWORKS[0]['id']
        res_dict = self.controller.show(self.admin_req, uuid)

        expected = copy.deepcopy(ADMIN_RESPONSE_TEMPLATE)
        expected['id'] = FAKE_NETWORKS[0]['id']
        expected['label'] = FAKE_NETWORKS[0]['name']

        self.assertEqual({'network': expected}, res_dict)

    def test_network_get_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, uuids.invalid)


class NetworksEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(NetworksEnforcementV21, self).setUp()
        self.controller = networks_v21.NetworkController()
        self.req = fakes.HTTPRequest.blank('')

    def test_show_policy_failed(self):
        rule_name = 'os_compute_api:os-networks:view'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        rule_name = 'os_compute_api:os-networks:view'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class NetworksDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(NetworksDeprecationTest, self).setUp()
        self.controller = networks_v21.NetworkController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_api_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
