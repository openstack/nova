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
import math
import uuid

import netaddr
from oslo.config import cfg
import webob

from nova.api.openstack.compute.contrib import networks_associate
from nova.api.openstack.compute.contrib import os_networks as networks
import nova.context
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes

CONF = cfg.CONF

FAKE_NETWORKS = [
    {
        'bridge': 'br100', 'vpn_public_port': 1000,
        'dhcp_start': '10.0.0.3', 'bridge_interface': 'eth0',
        'updated_at': '2011-08-16 09:26:13.048257',
        'id': 1, 'uuid': '20c8acc0-f747-4d71-a389-46d078ebf047',
        'cidr_v6': None, 'deleted_at': None,
        'gateway': '10.0.0.1', 'label': 'mynet_0',
        'project_id': '1234', 'rxtx_base': None,
        'vpn_private_address': '10.0.0.2', 'deleted': False,
        'vlan': 100, 'broadcast': '10.0.0.7',
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.0/29',
        'vpn_public_address': '127.0.0.1', 'multi_host': False,
        'dns1': None, 'dns2': None, 'host': 'nsokolov-desktop',
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': '2011-08-15 06:19:19.387525',
    },
    {
        'bridge': 'br101', 'vpn_public_port': 1001,
        'dhcp_start': '10.0.0.11', 'bridge_interface': 'eth0',
        'updated_at': None, 'id': 2, 'cidr_v6': None,
        'uuid': '20c8acc0-f747-4d71-a389-46d078ebf000',
        'deleted_at': None, 'gateway': '10.0.0.9',
        'label': 'mynet_1', 'project_id': None,
        'vpn_private_address': '10.0.0.10', 'deleted': False,
        'vlan': 101, 'broadcast': '10.0.0.15', 'rxtx_base': None,
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.10/29', 'vpn_public_address': None,
        'multi_host': False, 'dns1': None, 'dns2': None, 'host': None,
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': '2011-08-15 06:19:19.885495',
    },
]


FAKE_USER_NETWORKS = [
    {
        'id': 1, 'cidr': '10.0.0.0/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.1', 'broadcast': '10.0.0.7', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_0',
        'netmask_v6': None, 'uuid': '20c8acc0-f747-4d71-a389-46d078ebf047',
    },
    {
        'id': 2, 'cidr': '10.0.0.10/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.9', 'broadcast': '10.0.0.15', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_1',
        'netmask_v6': None, 'uuid': '20c8acc0-f747-4d71-a389-46d078ebf000',
    },
]

NEW_NETWORK = {
    "network": {
        "bridge_interface": "eth0",
        "cidr": "10.20.105.0/24",
        "label": "new net 111",
        "vlan_start": 111,
    }
}


class FakeNetworkAPI(object):

    _sentinel = object()
    _vlan_is_disabled = False

    def __init__(self):
        self.networks = copy.deepcopy(FAKE_NETWORKS)

    def disable_vlan(self):
        self._vlan_is_disabled = True

    def delete(self, context, network_id):
        for i, network in enumerate(self.networks):
            if network['id'] == network_id:
                del self.networks[0]
                return True
        raise exception.NetworkNotFoundForUUID(uuid=network_id)

    def disassociate(self, context, network_uuid):
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                network['project_id'] = None
                return True
        raise exception.NetworkNotFound(network_id=network_uuid)

    def associate(self, context, network_uuid, host=_sentinel,
                  project=_sentinel):
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                if host is not FakeNetworkAPI._sentinel:
                    network['host'] = host
                if project is not FakeNetworkAPI._sentinel:
                    network['project_id'] = project
                return True
        raise exception.NetworkNotFound(network_id=network_uuid)

    def add_network_to_project(self, context,
                               project_id, network_uuid=None):
        if self._vlan_is_disabled:
            raise NotImplementedError()
        if network_uuid:
            for network in self.networks:
                if network.get('project_id', None) is None:
                    network['project_id'] = project_id
                    return
            return
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                network['project_id'] = project_id
                return

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
        return nets

    def get(self, context, network_id):
        for network in self.networks:
            if network.get('uuid') == network_id:
                return network
        raise exception.NetworkNotFound(network_id=network_id)

    def create(self, context, **kwargs):
        subnet_bits = int(math.ceil(math.log(kwargs.get(
                        'network_size', CONF.network_size), 2)))
        fixed_net_v4 = netaddr.IPNetwork(kwargs['cidr'])
        prefixlen_v4 = 32 - subnet_bits
        subnets_v4 = list(fixed_net_v4.subnet(
                prefixlen_v4,
                count=kwargs.get('num_networks', CONF.num_networks)))
        new_networks = []
        new_id = max((net['id'] for net in self.networks))
        for index, subnet_v4 in enumerate(subnets_v4):
            new_id += 1
            net = {'id': new_id, 'uuid': str(uuid.uuid4())}

            net['cidr'] = str(subnet_v4)
            net['netmask'] = str(subnet_v4.netmask)
            net['gateway'] = kwargs.get('gateway') or str(subnet_v4[1])
            net['broadcast'] = str(subnet_v4.broadcast)
            net['dhcp_start'] = str(subnet_v4[2])

            for key in FAKE_NETWORKS[0].iterkeys():
                net.setdefault(key, kwargs.get(key))
            new_networks.append(net)
        self.networks += new_networks
        return new_networks


class NetworksTest(test.NoDBTestCase):

    def setUp(self):
        super(NetworksTest, self).setUp()
        self.fake_network_api = FakeNetworkAPI()
        self.controller = networks.NetworkController(
                                                self.fake_network_api)
        self.associate_controller = networks_associate\
            .NetworkAssociateActionController(self.fake_network_api)
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)

    @staticmethod
    def network_uuid_to_id(network):
        network['id'] = network['uuid']
        del network['uuid']

    def test_network_list_all_as_user(self):
        self.maxDiff = None
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks')
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, {'networks': []})

        project_id = req.environ["nova.context"].project_id
        cxt = req.environ["nova.context"]
        uuid = FAKE_NETWORKS[0]['uuid']
        self.fake_network_api.associate(context=cxt,
                                        network_uuid=uuid,
                                        project=project_id)
        res_dict = self.controller.index(req)
        expected = [FAKE_USER_NETWORKS[0]]
        for network in expected:
            self.network_uuid_to_id(network)
        self.assertEqual(res_dict, {'networks': expected})

    def test_network_list_all_as_admin(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks')
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.index(req)
        expected = copy.deepcopy(FAKE_NETWORKS)
        for network in expected:
            self.network_uuid_to_id(network)
        self.assertEqual(res_dict, {'networks': expected})

    def test_network_disassociate(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s/action' % uuid)
        res = self.controller._disassociate_host_and_project(
            req, uuid, {'disassociate': None})
        self.assertEqual(res.status_int, 202)
        self.assertIsNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_host_only(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s/action' % uuid)
        res = self.associate_controller._disassociate_host_only(
            req, uuid, {'disassociate_host': None})
        self.assertEqual(res.status_int, 202)
        self.assertIsNotNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_project_only(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s/action' % uuid)
        res = self.associate_controller._disassociate_project_only(
            req, uuid, {'disassociate_project': None})
        self.assertEqual(res.status_int, 202)
        self.assertIsNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNotNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._disassociate_host_and_project,
                          req, 100, {'disassociate': None})

    def test_network_get_as_user(self):
        uuid = FAKE_USER_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected = {'network': copy.deepcopy(FAKE_USER_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(res_dict, expected)

    def test_network_get_as_admin(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.show(req, uuid)
        expected = {'network': copy.deepcopy(FAKE_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(res_dict, expected)

    def test_network_get_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 100)

    def test_network_delete(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        res = self.controller.delete(req, 1)
        self.assertEqual(res.status_int, 202)

    def test_network_delete_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/100')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, 100)

    def test_network_add_vlan_disabled(self):
        self.fake_network_api.disable_vlan()
        uuid = FAKE_NETWORKS[1]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/add')
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.controller.add, req, {'id': uuid})

    def test_network_add(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/add')
        res = self.controller.add(req, {'id': uuid})
        self.assertEqual(res.status_int, 202)
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.show(req, uuid)
        self.assertEqual(res_dict['network']['project_id'], 'fake')

    def test_network_associate_with_host(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s/action' % uuid)
        res = self.associate_controller._associate_host(
            req, uuid, {'associate_host': "TestHost"})
        self.assertEqual(res.status_int, 202)
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        req.environ["nova.context"].is_admin = True
        res_dict = self.controller.show(req, uuid)
        self.assertEqual(res_dict['network']['host'], 'TestHost')

    def test_network_create(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks')
        res_dict = self.controller.create(req, NEW_NETWORK)
        self.assertIn('network', res_dict)
        uuid = res_dict['network']['id']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        self.assertTrue(res_dict['network']['label'].
                        startswith(NEW_NETWORK['network']['label']))

    def test_network_create_large(self):
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks')
        large_network = copy.deepcopy(NEW_NETWORK)
        large_network['network']['cidr'] = '128.0.0.0/4'
        res_dict = self.controller.create(req, large_network)
        self.assertEqual(res_dict['network']['cidr'],
                         large_network['network']['cidr'])
