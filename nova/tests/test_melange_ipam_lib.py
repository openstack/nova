# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from nova import db
from nova import exception
from nova import flags
from nova import test
from nova.network.quantum import melange_connection
from nova.network.quantum import melange_ipam_lib

FLAGS = flags.FLAGS


class MelangeIpamLibTestCase(test.TestCase):
    def setUp(self):
        super(MelangeIpamLibTestCase, self).setUp()
        self.m_conn = self.mox.CreateMock(melange_connection.MelangeConnection)
        self.ipam = melange_ipam_lib.QuantumMelangeIPAMLib()
        self.ipam.m_conn = self.m_conn

    def _block_list(self, id='id', cidr='cidr', network_id='network_id'):
        return {'ip_blocks': [{'id': id,
                                'cidr': cidr,
                               'network_id': network_id}]}

    def test_allocate_fixed_ips_extracts_address(self):
        self.m_conn.allocate_ip('quantum_net_id', 'network_tenant_id',
                                'vif_ref_uuid', 'project_id',
                                'vif_ref_address').AndReturn(
                                                [{'address': 'ip_address'}])

        self.mox.ReplayAll()

        ips = self.ipam.allocate_fixed_ips('context',
                                           'project_id',
                                           'quantum_net_id',
                                           'network_tenant_id',
                                           {'uuid': 'vif_ref_uuid',
                                            'address': 'vif_ref_address'})
        self.assertEqual(ips[0], 'ip_address')

    def test_delete_subnets_by_net_id_deletes_block(self):
        context = self.mox.CreateMockAnything()
        context.elevated().AndReturn('elevated')

        self.m_conn.get_blocks('project_id').AndReturn(
                                        self._block_list(id='block_id'))
        self.m_conn.delete_block('block_id', 'project_id')

        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        db.network_get_by_uuid('elevated', 'network_id').AndReturn(
                                                         {'id': 'network_id'})

        self.mox.StubOutWithMock(db, 'network_delete_safe')
        db.network_delete_safe(context, 'network_id')

        self.mox.ReplayAll()
        self.ipam.delete_subnets_by_net_id(context, 'network_id', 'project_id')

    def test_get_networks_by_tenant_gets_all_networks(self):
        block_list = self._block_list(network_id='net_1')
        block_list['ip_blocks'] += self._block_list(
                                        network_id='net_2')['ip_blocks']

        self.m_conn.get_blocks('tenant_id').AndReturn(block_list)

        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        db.network_get_by_uuid('admin_context', 'net_1').AndReturn('network1')
        db.network_get_by_uuid('admin_context', 'net_2').AndReturn('network2')

        self.mox.ReplayAll()
        values = self.ipam.get_networks_by_tenant('admin_context', 'tenant_id')
        self.assertEquals(values, ['network1', 'network2'])

    def test_get_global_networks(self):
        FLAGS.quantum_default_tenant_id = 'quantum_default_tenant_id'
        self.mox.StubOutWithMock(self.ipam, 'get_networks_by_tenant')
        self.ipam.get_networks_by_tenant('admin_context',
                                    'quantum_default_tenant_id')

        self.mox.ReplayAll()

        self.ipam.get_global_networks('admin_context')

    def test_get_project_networks(self):
        context = self.mox.CreateMockAnything()
        context.elevated().AndReturn('elevated')

        networks = [{'project_id': 1}, {'project_id': None}]

        self.mox.StubOutWithMock(db, 'network_get_all')
        db.network_get_all('elevated').AndReturn(networks)

        self.mox.ReplayAll()
        values = self.ipam.get_project_networks(context)
        self.assertEquals(values, [networks[0]])

    def test_get_project_and_global_net_ids__by_priority(self):
        context = self.mox.CreateMockAnything()
        context.elevated().AndReturn('elevated')

        FLAGS.quantum_default_tenant_id = 'default_tenant_id'

        net1 = {'uuid': 'net1_uuid', 'priority': 'net1_priority'}
        net2 = {'uuid': 'net2_uuid', 'priority': 'net2_priority'}

        self.mox.StubOutWithMock(self.ipam, 'get_networks_by_tenant')
        self.ipam.get_networks_by_tenant('elevated',
                                         'project_id').AndReturn([net1])
        self.ipam.get_networks_by_tenant('elevated',
                                         'default_tenant_id').AndReturn([net2])
        self.mox.ReplayAll()
        self.ipam.get_project_and_global_net_ids(context, 'project_id')

    def test_get_tenant_id_by_net_id_returns_id(self):
        FLAGS.quantum_default_tenant_id = 'qdti'

        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                      'qdti').AndReturn({})
        self.mox.ReplayAll()
        value = self.ipam.get_tenant_id_by_net_id('context', 'net_id',
                                          'vif_id', 'project_id')
        self.assertEqual(value, 'qdti')

    def test_get_tenant_id_by_net_id_returns_none_if_none_found(self):
        FLAGS.quantum_default_tenant_id = 'qdti'

        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                        'qdti').AndRaise(KeyError())
        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                        'project_id').AndRaise(KeyError())
        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                        None).AndRaise(KeyError())
        self.mox.ReplayAll()
        value = self.ipam.get_tenant_id_by_net_id('context', 'net_id',
                                          'vif_id', 'project_id')
        self.assertEqual(value, None)

    def test_get_subnets_by_net_id(self):
        ips = [{'ip_block': {'network_id': 'network_id',
                            'id': 'id',
                            'cidr': 'cidr',
                            'gateway': 'gateway',
                            'broadcast': 'broadcast',
                            'netmask': 'netmask',
                            'dns1': 'dns1',
                            'dns2': 'dns2'},
                'version': 4}]

        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                      'tenant_id').AndReturn(ips)

        self.mox.ReplayAll()
        value = self.ipam.get_subnets_by_net_id('context', 'tenant_id',
                                                'net_id', 'vif_id')
        self.assertEquals(value[0]['cidr'], 'cidr')

    def test_get_routes_by_ip_block(self):
        self.m_conn.get_routes('block_id', 'project_id')
        self.mox.ReplayAll()
        self.ipam.get_routes_by_ip_block('context', 'block_id', 'project_id')

    def test_get_v4_ips_by_interface(self):
        self.mox.StubOutWithMock(self.ipam, '_get_ips_by_interface')
        self.ipam._get_ips_by_interface('context', 'net_id', 'vif_id',
                                        'project_id', 4)
        self.mox.ReplayAll()
        self.ipam.get_v4_ips_by_interface('context', 'net_id', 'vif_id',
                                          'project_id')

    def test_get_v6_ips_by_interface(self):
        self.mox.StubOutWithMock(self.ipam, '_get_ips_by_interface')
        self.ipam._get_ips_by_interface('context', 'net_id', 'vif_id',
                                        'project_id', 6)
        self.mox.ReplayAll()
        self.ipam.get_v6_ips_by_interface('context', 'net_id', 'vif_id',
                                          'project_id')

    def test_get_ips_by_interface(self):
        ips = [{'address': '10.10.10.10'}, {'address': '2001::CAFE'}]
        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                      'tenant_id').AndReturn(ips)
        self.m_conn.get_allocated_ips('net_id', 'vif_id',
                                      'tenant_id').AndReturn(ips)
        self.mox.ReplayAll()
        values = self.ipam._get_ips_by_interface('context', 'net_id', 'vif_id',
                                        'tenant_id', 4)
        self.assertEquals(values, ["10.10.10.10"])
        values = self.ipam._get_ips_by_interface('context', 'net_id', 'vif_id',
                                        'tenant_id', 6)
        self.assertEquals(values, ["2001::CAFE"])

    def test_get_instance_ids_by_ip_address(self):
        ips = [{'used_by_device': 'some_vif_uuid'}]
        self.m_conn.get_allocated_ips_by_address('ip').AndReturn(ips)

        self.mox.ReplayAll()
        uuid = self.ipam.get_instance_ids_by_ip_address('context', 'ip')
        self.assertEqual(uuid, ['some_vif_uuid'])

    def test_verify_subnet_exists(self):
        blocks = {'ip_blocks': [{'network_id': 'quantum_net_id'}]}
        self.m_conn.get_blocks('tenant_id').AndReturn(blocks)
        self.mox.ReplayAll()
        value = self.ipam.verify_subnet_exists('context', 'tenant_id',
                                       'quantum_net_id')
        self.assertEquals(value, True)

    def test_deallocate_ips_by_vif(self):
        self.m_conn.deallocate_ips('net_id', 'uuid', 'tenant_id')
        self.mox.ReplayAll()
        self.ipam.deallocate_ips_by_vif('context', 'tenant_id', 'net_id',
                {'uuid': 'uuid'})

    def test_get_allocated_ips(self):
        ips = [{'address': 'ip_address', 'interface_id': 'interface_id'}]
        self.m_conn.get_allocated_ips_for_network('subnet_id',
                                                  'project_id').AndReturn(ips)
        self.mox.ReplayAll()
        self.ipam.get_allocated_ips('context', 'subnet_id', 'project_id')

    def test_create_vif(self):
        self.m_conn.create_vif('vif_id', 'instance_id', 'project_id')
        self.mox.ReplayAll()
        self.ipam.create_vif('vif_id', 'instance_id', 'project_id')

    def test_get_floating_ips_by_fixed_address(self):
        value = self.ipam.get_floating_ips_by_fixed_address('context',
                                                      'fixed_address')
        self.assertEquals(value, [])
