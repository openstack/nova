#    Copyright 2014 Red Hat, Inc.
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
import netaddr

from nova.objects import network as network_obj
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


fake_network = {
    'deleted': False,
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'id': 1,
    'label': 'Fake Network',
    'injected': False,
    'cidr': '192.168.1.0/24',
    'cidr_v6': '1234::/64',
    'multi_host': False,
    'netmask': '255.255.255.0',
    'gateway': '192.168.1.1',
    'broadcast': '192.168.1.255',
    'netmask_v6': 64,
    'gateway_v6': '1234::1',
    'bridge': 'br100',
    'bridge_interface': 'eth0',
    'dns1': '8.8.8.8',
    'dns2': '8.8.4.4',
    'vlan': None,
    'vpn_public_address': None,
    'vpn_public_port': None,
    'vpn_private_address': None,
    'dhcp_start': '192.168.1.10',
    'rxtx_base': None,
    'project_id': None,
    'priority': None,
    'host': None,
    'uuid': uuids.network_instance,
    'mtu': None,
    'dhcp_server': '192.168.1.1',
    'enable_dhcp': True,
    'share_address': False,
}


class _TestNetworkObject(object):
    def _compare(self, obj, db_obj):
        for field in obj.fields:
            db_val = db_obj[field]
            obj_val = obj[field]
            if isinstance(obj_val, netaddr.IPAddress):
                obj_val = str(obj_val)
            if isinstance(obj_val, netaddr.IPNetwork):
                obj_val = str(obj_val)
            if field == 'netmask_v6':
                db_val = str(netaddr.IPNetwork('1::/%i' % db_val).netmask)
            self.assertEqual(db_val, obj_val)

    @mock.patch('nova.db.network_get')
    def test_get_by_id(self, get):
        get.return_value = fake_network
        network = network_obj.Network.get_by_id(self.context, 'foo')
        self._compare(network, fake_network)
        get.assert_called_once_with(self.context, 'foo',
                                    project_only='allow_none')

    @mock.patch('nova.db.network_get_by_uuid')
    def test_get_by_uuid(self, get):
        get.return_value = fake_network
        network = network_obj.Network.get_by_uuid(self.context, 'foo')
        self._compare(network, fake_network)
        get.assert_called_once_with(self.context, 'foo')

    @mock.patch('nova.db.network_get_by_cidr')
    def test_get_by_cidr(self, get):
        get.return_value = fake_network
        network = network_obj.Network.get_by_cidr(self.context,
                                                  '192.168.1.0/24')
        self._compare(network, fake_network)
        get.assert_called_once_with(self.context, '192.168.1.0/24')

    @mock.patch('nova.db.network_update')
    @mock.patch('nova.db.network_set_host')
    def test_save(self, set_host, update):
        result = dict(fake_network, injected=True)
        network = network_obj.Network._from_db_object(self.context,
                                                      network_obj.Network(),
                                                      fake_network)
        network.obj_reset_changes()
        network.save()
        network.label = 'bar'
        update.return_value = result
        network.save()
        update.assert_called_once_with(self.context, network.id,
                                       {'label': 'bar'})
        self.assertFalse(set_host.called)
        self._compare(network, result)

    @mock.patch('nova.db.network_update')
    @mock.patch('nova.db.network_set_host')
    @mock.patch('nova.db.network_get')
    def test_save_with_host(self, get, set_host, update):
        result = dict(fake_network, injected=True)
        network = network_obj.Network._from_db_object(self.context,
                                                      network_obj.Network(),
                                                      fake_network)
        network.obj_reset_changes()
        network.host = 'foo'
        get.return_value = result
        network.save()
        set_host.assert_called_once_with(self.context, network.id, 'foo')
        self.assertFalse(update.called)
        self._compare(network, result)

    @mock.patch('nova.db.network_update')
    @mock.patch('nova.db.network_set_host')
    def test_save_with_host_and_other(self, set_host, update):
        result = dict(fake_network, injected=True)
        network = network_obj.Network._from_db_object(self.context,
                                                      network_obj.Network(),
                                                      fake_network)
        network.obj_reset_changes()
        network.host = 'foo'
        network.label = 'bar'
        update.return_value = result
        network.save()
        set_host.assert_called_once_with(self.context, network.id, 'foo')
        update.assert_called_once_with(self.context, network.id,
                                       {'label': 'bar'})
        self._compare(network, result)

    @mock.patch('nova.db.network_associate')
    def test_associate(self, associate):
        network_obj.Network.associate(self.context, 'project',
                                      network_id=123)
        associate.assert_called_once_with(self.context, 'project',
                                          network_id=123, force=False)

    @mock.patch('nova.db.network_disassociate')
    def test_disassociate(self, disassociate):
        network_obj.Network.disassociate(self.context, 123,
                                         host=True, project=True)
        disassociate.assert_called_once_with(self.context, 123, True, True)

    @mock.patch('nova.db.network_create_safe')
    def test_create(self, create):
        create.return_value = fake_network
        network = network_obj.Network(context=self.context, label='foo')
        network.create()
        create.assert_called_once_with(self.context, {'label': 'foo'})
        self._compare(network, fake_network)

    @mock.patch('nova.db.network_delete_safe')
    def test_destroy(self, delete):
        network = network_obj.Network(context=self.context, id=123)
        network.destroy()
        delete.assert_called_once_with(self.context, 123)
        self.assertTrue(network.deleted)
        self.assertNotIn('deleted', network.obj_what_changed())

    @mock.patch('nova.db.network_get_all')
    def test_get_all(self, get_all):
        get_all.return_value = [fake_network]
        networks = network_obj.NetworkList.get_all(self.context)
        self.assertEqual(1, len(networks))
        get_all.assert_called_once_with(self.context, 'allow_none')
        self._compare(networks[0], fake_network)

    @mock.patch('nova.db.network_get_all_by_uuids')
    def test_get_all_by_uuids(self, get_all):
        get_all.return_value = [fake_network]
        networks = network_obj.NetworkList.get_by_uuids(self.context,
                                                        ['foo'])
        self.assertEqual(1, len(networks))
        get_all.assert_called_once_with(self.context, ['foo'], 'allow_none')
        self._compare(networks[0], fake_network)

    @mock.patch('nova.db.network_get_all_by_host')
    def test_get_all_by_host(self, get_all):
        get_all.return_value = [fake_network]
        networks = network_obj.NetworkList.get_by_host(self.context, 'host')
        self.assertEqual(1, len(networks))
        get_all.assert_called_once_with(self.context, 'host')
        self._compare(networks[0], fake_network)

    @mock.patch('nova.db.network_in_use_on_host')
    def test_in_use_on_host(self, in_use):
        in_use.return_value = True
        self.assertTrue(network_obj.Network.in_use_on_host(self.context,
                                                           123, 'foo'))
        in_use.assert_called_once_with(self.context, 123, 'foo')

    @mock.patch('nova.db.project_get_networks')
    def test_get_all_by_project(self, get_nets):
        get_nets.return_value = [fake_network]
        networks = network_obj.NetworkList.get_by_project(self.context, 123)
        self.assertEqual(1, len(networks))
        get_nets.assert_called_once_with(self.context, 123, associate=True)
        self._compare(networks[0], fake_network)

    def test_compat_version_1_1(self):
        network = network_obj.Network._from_db_object(self.context,
                                                      network_obj.Network(),
                                                      fake_network)
        primitive = network.obj_to_primitive(target_version='1.1')
        self.assertNotIn('mtu', primitive)
        self.assertNotIn('enable_dhcp', primitive)
        self.assertNotIn('dhcp_server', primitive)
        self.assertNotIn('share_address', primitive)


class TestNetworkObject(test_objects._LocalTest,
                        _TestNetworkObject):
    pass


class TestRemoteNetworkObject(test_objects._RemoteTest,
                              _TestNetworkObject):
    pass
