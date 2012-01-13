# Copyright 2011 Grid Dynamics
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

import copy

import webob

from nova.api.openstack.compute.contrib import networks
from nova import context
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


FAKE_NETWORKS = [
    {
        'bridge': 'br100', 'vpn_public_port': 1000,
        'dhcp_start': '10.0.0.3', 'bridge_interface': 'eth0',
        'updated_at': '2011-08-16 09:26:13.048257', 'id': 1,
        'cidr_v6': None, 'deleted_at': None,
        'gateway': '10.0.0.1', 'label': 'mynet_0',
        'project_id': '1234',
        'vpn_private_address': '10.0.0.2', 'deleted': False,
        'vlan': 100, 'broadcast': '10.0.0.7',
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.0/29',
        'vpn_public_address': '127.0.0.1', 'multi_host': False,
        'dns1': None, 'host': 'nsokolov-desktop',
        'gateway_v6': None, 'netmask_v6': None,
        'created_at': '2011-08-15 06:19:19.387525',
    },
    {
        'bridge': 'br101', 'vpn_public_port': 1001,
        'dhcp_start': '10.0.0.11', 'bridge_interface': 'eth0',
        'updated_at': None, 'id': 2, 'cidr_v6': None,
        'deleted_at': None, 'gateway': '10.0.0.9',
        'label': 'mynet_1', 'project_id': None,
        'vpn_private_address': '10.0.0.10', 'deleted': False,
        'vlan': 101, 'broadcast': '10.0.0.15',
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.10/29', 'vpn_public_address': None,
        'multi_host': False, 'dns1': None, 'host': None,
        'gateway_v6': None, 'netmask_v6': None,
        'created_at': '2011-08-15 06:19:19.885495',
    },
]


class FakeNetworkAPI(object):

    def __init__(self):
        self.networks = copy.deepcopy(FAKE_NETWORKS)

    def delete(self, context, network_id):
        for i, network in enumerate(self.networks):
            if network['id'] == network_id:
                del self.networks[0]
                return True
        raise exception.NetworkNotFound()

    #NOTE(bcwaldon): this does nothing other than check for existance
    def disassociate(self, context, network_id):
        for i, network in enumerate(self.networks):
            if network['id'] == network_id:
                return True
        raise exception.NetworkNotFound()

    def get_all(self, context):
        return self.networks

    def get(self, context, network_id):
        for network in self.networks:
            if network['id'] == network_id:
                return network
        raise exception.NetworkNotFound()


class NetworksTest(test.TestCase):

    def setUp(self):
        super(NetworksTest, self).setUp()
        self.flags(allow_admin_api=True)
        self.fake_network_api = FakeNetworkAPI()
        self.controller = networks.NetworkController(self.fake_network_api)
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.context = context.RequestContext('user', '1234', is_admin=True)

    def test_network_list_all(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks')
        res_dict = self.controller.index(req)
        self.assertEquals(res_dict, {'networks': FAKE_NETWORKS})

    def test_network_disassociate(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/1/action')
        res = self.controller.action(req, 1, {'disassociate': None})
        self.assertEqual(res.status_int, 202)

    def test_network_disassociate_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.action,
                          req, 100, {'disassociate': None})

    def test_network_get(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/1')
        res_dict = self.controller.show(req, 1)
        expected = {'network': FAKE_NETWORKS[0]}
        self.assertEqual(res_dict, expected)

    def test_network_get_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 100)

    def test_network_delete(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/1')
        res = self.controller.delete(req, 1)
        self.assertEqual(res.status_int, 202)

    def test_network_delete_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, 100)
