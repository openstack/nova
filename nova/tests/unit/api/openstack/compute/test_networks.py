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
import datetime

import iso8601
from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import networks as networks_v21
import nova.context
from nova import exception
from nova.network.neutronv2 import api as neutron
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
import nova.utils


CONF = cfg.CONF
FAKE_NETWORK_PROJECT_ID = '6133f8b603924f45bc0c9e21f6df12fa'

UTC = iso8601.UTC
FAKE_NETWORKS = [
    {
        'bridge': 'br100', 'vpn_public_port': 1000,
        'dhcp_start': '10.0.0.3', 'bridge_interface': 'eth0',
        'updated_at': datetime.datetime(2011, 8, 16, 9, 26, 13, 48257,
                                        tzinfo=UTC),
        'id': 1, 'uuid': uuids.network_1,
        'cidr_v6': None, 'deleted_at': None,
        'gateway': '10.0.0.1', 'label': 'mynet_0',
        'project_id': FAKE_NETWORK_PROJECT_ID, 'rxtx_base': None,
        'vpn_private_address': '10.0.0.2', 'deleted': False,
        'vlan': 100, 'broadcast': '10.0.0.7',
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.0/29',
        'vpn_public_address': '127.0.0.1', 'multi_host': False,
        'dns1': None, 'dns2': None, 'host': 'nsokolov-desktop',
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': datetime.datetime(2011, 8, 15, 6, 19, 19, 387525,
                                        tzinfo=UTC),
        'mtu': None, 'dhcp_server': '10.0.0.1', 'enable_dhcp': True,
        'share_address': False,
    },
    {
        'bridge': 'br101', 'vpn_public_port': 1001,
        'dhcp_start': '10.0.0.11', 'bridge_interface': 'eth0',
        'updated_at': None, 'id': 2, 'cidr_v6': None,
        'uuid': uuids.network_2,
        'deleted_at': None, 'gateway': '10.0.0.9',
        'label': 'mynet_1', 'project_id': None,
        'vpn_private_address': '10.0.0.10', 'deleted': False,
        'vlan': 101, 'broadcast': '10.0.0.15', 'rxtx_base': None,
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.10/29', 'vpn_public_address': None,
        'multi_host': False, 'dns1': None, 'dns2': None, 'host': None,
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': datetime.datetime(2011, 8, 15, 6, 19, 19, 885495,
                                        tzinfo=UTC),
        'mtu': None, 'dhcp_server': '10.0.0.9', 'enable_dhcp': True,
        'share_address': False,
    },
]


FAKE_USER_NETWORKS = [
    {
        'id': 1, 'cidr': '10.0.0.0/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.1', 'broadcast': '10.0.0.7', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_0',
        'netmask_v6': None, 'uuid': uuids.network_1,
    },
    {
        'id': 2, 'cidr': '10.0.0.10/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.9', 'broadcast': '10.0.0.15', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_1',
        'netmask_v6': None, 'uuid': uuids.network_2,
    },
]

NEW_NETWORK = {
    "network": {
        "bridge_interface": "eth0",
        "cidr": "10.20.105.0/24",
        "label": "new net 111",
        "vlan_start": 111,
        "multi_host": False,
        'dhcp_server': '10.0.0.1',
        'enable_dhcp': True,
        'share_address': False,
    }
}


class FakeNetworkAPI(object):

    _sentinel = object()

    def __init__(self):
        self.networks = copy.deepcopy(FAKE_NETWORKS)

    def get_all(self, context):
        return self._fake_db_network_get_all(context, project_only=True)

    def _fake_db_network_get_all(self, context, project_only="allow_none"):
        project_id = context.project_id
        nets = self.networks
        if nova.context.is_user_context(context) and project_only:
            if project_only == 'allow_none':
                nets = [n for n in self.networks
                        if (n['project_id'] == project_id or
                            n['project_id'] is None)]
            else:
                nets = [n for n in self.networks
                        if n['project_id'] == project_id]
        objs = [objects.Network._from_db_object(context,
                                                objects.Network(),
                                                net)
                for net in nets]
        return objects.NetworkList(objects=objs)

    def get(self, context, network_id):
        for network in self.networks:
            if network.get('uuid') == network_id:
                if 'injected' in network and network['injected'] is None:
                    # NOTE: This is a workaround for passing unit tests.
                    # When using nova-network, 'injected' value should be
                    # boolean because of the definition of objects.Network().
                    # However, 'injected' value can be None if neutron.
                    # So here changes the value to False just for passing
                    # following _from_db_object().
                    network['injected'] = False
                return objects.Network._from_db_object(context,
                                                       objects.Network(),
                                                       network)
        raise exception.NetworkNotFound(network_id=network_id)


class NetworksTestV21(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(NetworksTestV21, self).setUp()
        # TODO(stephenfin): Consider using then NeutronFixture here
        self.fake_network_api = FakeNetworkAPI()
        self._setup()
        fakes.stub_out_networking(self)
        self.new_network = copy.deepcopy(NEW_NETWORK)
        self.non_admin_req = fakes.HTTPRequest.blank(
            '', project_id=fakes.FAKE_PROJECT_ID)
        self.admin_req = fakes.HTTPRequest.blank('',
                              project_id=fakes.FAKE_PROJECT_ID,
                              use_admin_context=True)

    def _setup(self):
        self.controller = networks_v21.NetworkController(
            self.fake_network_api)
        self.neutron_ctrl = networks_v21.NetworkController(
            neutron.API())
        self.req = fakes.HTTPRequest.blank('',
                                           project_id=fakes.FAKE_PROJECT_ID)

    def _check_status(self, res, method, code):
        self.assertEqual(method.wsgi_code, code)

    @staticmethod
    def network_uuid_to_id(network):
        network['id'] = network['uuid']
        del network['uuid']

    def test_network_list_all_as_user(self):
        self.maxDiff = None
        res_dict = self.controller.index(self.non_admin_req)
        self.assertEqual(res_dict, {'networks': []})

    def test_network_list_all_as_admin(self):
        res_dict = self.controller.index(self.admin_req)
        expected = copy.deepcopy(FAKE_NETWORKS)
        for network in expected:
            self.network_uuid_to_id(network)
        self.assertEqual({'networks': expected}, res_dict)

    def test_network_get_as_user(self):
        uuid = FAKE_USER_NETWORKS[0]['uuid']
        res_dict = self.controller.show(self.non_admin_req, uuid)
        expected = {'network': copy.deepcopy(FAKE_USER_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(expected, res_dict)

    def test_network_get_as_admin(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        res_dict = self.controller.show(self.admin_req, uuid)
        expected = {'network': copy.deepcopy(FAKE_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(expected, res_dict)

    def test_network_get_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, 100)


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
