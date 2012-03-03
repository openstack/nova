# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011,2012 Nicira, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mox

from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from nova import exception
from nova import flags
from nova import log as logging
from nova.network.quantum import client as quantum_client
from nova.network.quantum import fake_client
from nova.network.quantum import manager as quantum_manager
from nova.network.quantum import quantum_connection
from nova.network.quantum import melange_connection
from nova.network.quantum import melange_ipam_lib

from nova import test
from nova import utils

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


networks = [{'label': 'project1-net1',
             'injected': False,
             'multi_host': False,
             'cidr': '100.168.0.0/24',
             'cidr_v6': '100:1db8::/64',
             'gateway_v6': '100:1db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '100.168.0.1',
             'broadcast': '100.168.0.255',
             'dns1': '8.8.8.8',
             'vlan': None,
             'host': None,
             'vpn_public_address': None,
             'project_id': 'fake_project1',
             'priority': 1},
            {'label': 'project2-net1',
             'injected': False,
             'multi_host': False,
             'cidr': '101.168.1.0/24',
             'cidr_v6': '101:1db9::/64',
             'gateway_v6': '101:1db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '101.168.1.1',
             'broadcast': '101.168.1.255',
             'dns1': '8.8.8.8',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project2',
             'priority': 1},
             {'label': "public",
             'injected': False,
             'multi_host': False,
             'cidr': '102.0.0.0/24',
             'cidr_v6': '102:1dba::/64',
             'gateway_v6': '102:1dba::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '102.0.0.1',
             'broadcast': '102.0.0.255',
             'dns1': '8.8.8.8',
             'vlan': None,
             'host': None,
             'project_id': None,
             'priority': 0},
             {'label': "project2-net2",
             'injected': False,
             'multi_host': False,
             'cidr': '103.0.0.0/24',
             'cidr_v6': '103:1dbb::/64',
             'gateway_v6': '103:1dbb::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '103.0.0.1',
             'broadcast': '103.0.0.255',
             'dns1': '8.8.8.8',
             'vlan': None,
             'host': None,
             'project_id': "fake_project2",
             'priority': 2}]


class QuantumConnectionTestCase(test.TestCase):

    def test_connection(self):
        fc = fake_client.FakeClient(LOG)
        qc = quantum_connection.QuantumClientConnection(client=fc)
        t = "tenant1"
        net1_name = "net1"
        net1_uuid = qc.create_network(t, net1_name)
        self.assertEquals(net1_name, qc.get_network_name(t, net1_uuid))
        self.assertTrue(qc.network_exists(t, net1_uuid))
        self.assertFalse(qc.network_exists(t, "fake-uuid"))
        self.assertFalse(qc.network_exists("fake-tenant", net1_uuid))

        nets = qc.get_networks(t)['networks']
        self.assertEquals(len(nets), 1)
        self.assertEquals(nets[0]['id'], net1_uuid)

        num_ports = 10
        for i in range(0, num_ports):
            qc.create_and_attach_port(t, net1_uuid,
                                'iface' + str(i), state='ACTIVE')

        self.assertEquals(len(qc.get_attached_ports(t, net1_uuid)), num_ports)

        for i in range(0, num_ports):
            port_uuid = qc.get_port_by_attachment(t, net1_uuid,
                                'iface' + str(i))
            self.assertTrue(port_uuid)
            qc.detach_and_delete_port(t, net1_uuid, port_uuid)

        self.assertEquals(len(qc.get_attached_ports(t, net1_uuid)), 0)

        # test port not found
        qc.create_and_attach_port(t, net1_uuid, 'foo', state='ACTIVE')
        port_uuid = qc.get_port_by_attachment(t, net1_uuid, 'foo')
        qc.detach_and_delete_port(t, net1_uuid, port_uuid)
        self.assertRaises(quantum_client.QuantumNotFoundException,
                            qc.detach_and_delete_port, t,
                            net1_uuid, port_uuid)

        qc.delete_network(t, net1_uuid)
        self.assertFalse(qc.network_exists(t, net1_uuid))
        self.assertEquals(len(qc.get_networks(t)['networks']), 0)

        self.assertRaises(quantum_client.QuantumNotFoundException,
                            qc.get_network_name, t, net1_uuid)


# this is a base class to be used by other QuantumManager Test classes
class QuantumNovaTestCase(test.TestCase):

    def setUp(self):
        super(QuantumNovaTestCase, self).setUp()

        self.flags(quantum_use_dhcp=True)
        self.flags(l3_lib="nova.network.l3.LinuxNetL3")
        linuxdrv = "nova.network.linux_net.LinuxOVSInterfaceDriver"
        self.flags(linuxnet_interface_driver=linuxdrv)
        fc = fake_client.FakeClient(LOG)
        qc = quantum_connection.QuantumClientConnection(client=fc)

        self.net_man = quantum_manager.QuantumManager(
                ipam_lib="nova.network.quantum.nova_ipam_lib",
                q_conn=qc)

        def func(arg1, arg2):
            pass

        def func2(arg1, arg2, arg3):
            pass

        def func1(arg1):
            pass

        self.net_man.driver.update_dhcp_hostfile_with_text = func
        self.net_man.driver.restart_dhcp = func2
        self.net_man.driver.kill_dhcp = func1

        # Tests seem to create some networks by default, which
        # we don't want.  So we delete them.

        ctx = context.RequestContext('user1', 'fake_project1').elevated()
        for n in db.network_get_all(ctx):
            db.network_delete_safe(ctx, n['id'])

        # Other unit tests (e.g., test_compute.py) have a nasty
        # habit of of creating fixed IPs and not cleaning up, which
        # can confuse these tests, so we remove all existing fixed
        # ips before starting.
        session = get_session()
        result = session.query(models.FixedIp).all()
        with session.begin():
            for fip_ref in result:
                session.delete(fip_ref)

        self.net_man.init_host()

    def _create_network(self, n):
        ctx = context.RequestContext('user1', n['project_id'])
        nwks = self.net_man.create_networks(
            ctx,
            label=n['label'], cidr=n['cidr'],
            multi_host=n['multi_host'],
            num_networks=1, network_size=256,
            cidr_v6=n['cidr_v6'],
            gateway=n['gateway'],
            gateway_v6=n['gateway_v6'], bridge=None,
            bridge_interface=None, dns1=n['dns1'],
            project_id=n['project_id'],
            priority=n['priority'])
        n['uuid'] = nwks[0]['uuid']


class QuantumAllocationTestCase(QuantumNovaTestCase):
    def test_get_network_in_db(self):
        context = self.mox.CreateMockAnything()
        context.elevated().AndReturn('elevated')
        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        self.net_man.context = context
        db.network_get_by_uuid('elevated', 'quantum_net_id').AndReturn(
                                                                {'uuid': 1})

        self.mox.ReplayAll()

        network = self.net_man.get_network(context, ('quantum_net_id',
                                                     'net_tenant_id'))
        self.assertEquals(network['quantum_net_id'], 'quantum_net_id')
        self.assertEquals(network['uuid'], 1)

    def test_get_network_not_in_db(self):
        context = self.mox.CreateMockAnything()
        context.elevated().AndReturn('elevated')
        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        self.net_man.context = context
        db.network_get_by_uuid('elevated', 'quantum_net_id').AndReturn(None)

        self.mox.ReplayAll()

        network = self.net_man.get_network(context, ('quantum_net_id',
                                                     'net_tenant_id'))
        self.assertEquals(network['quantum_net_id'], 'quantum_net_id')
        self.assertEquals(network['uuid'], 'quantum_net_id')


class QuantumDeallocationTestCase(QuantumNovaTestCase):
    def test_deallocate_port(self):
        quantum = self.mox.CreateMock(
                                quantum_connection.QuantumClientConnection)
        quantum.get_port_by_attachment('q_tenant_id', 'net_id',
                                       'interface_id').AndReturn('port_id')
        quantum.detach_and_delete_port('q_tenant_id', 'net_id', 'port_id')
        self.net_man.q_conn = quantum

        self.mox.ReplayAll()

        self.net_man.deallocate_port('interface_id', 'net_id', 'q_tenant_id',
                                     'instance_id')

    def test_deallocate_port_logs_error(self):
        quantum = self.mox.CreateMock(
            quantum_connection.QuantumClientConnection)
        quantum.get_port_by_attachment('q_tenant_id', 'net_id',
                            'interface_id').AndRaise(Exception)
        self.net_man.q_conn = quantum

        self.mox.StubOutWithMock(quantum_manager.LOG, 'exception')
        quantum_manager.LOG.exception(mox.Regex(r'port deallocation failed'))

        self.mox.ReplayAll()

        self.net_man.deallocate_port('interface_id', 'net_id', 'q_tenant_id',
                                     'instance_id')

    def test_deallocate_ip_address(self):
        ipam = self.mox.CreateMock(melange_ipam_lib.QuantumMelangeIPAMLib)
        ipam.get_tenant_id_by_net_id('context', 'net_id', {'uuid': 1},
                                     'project_id').AndReturn('ipam_tenant_id')
        self.net_man.ipam = ipam
        self.mox.ReplayAll()
        self.net_man.deallocate_ip_address('context', 'net_id', 'project_id',
                {'uuid': 1}, 'instance_id')

    def test_deallocate_ip_address(self):
        ipam = self.mox.CreateMock(melange_ipam_lib.QuantumMelangeIPAMLib)
        ipam.get_tenant_id_by_net_id('context', 'net_id', {'uuid': 1},
                                     'project_id').AndRaise(Exception())
        self.net_man.ipam = ipam

        self.mox.StubOutWithMock(quantum_manager.LOG, 'exception')
        quantum_manager.LOG.exception(mox.Regex(r'ipam deallocation failed'))

        self.mox.ReplayAll()
        self.net_man.deallocate_ip_address('context', 'net_id', 'project_id',
                {'uuid': 1}, 'instance_id')


class QuantumManagerTestCase(QuantumNovaTestCase):
    def test_create_and_delete_nets(self):
        self._create_nets()
        self._delete_nets()

    def _create_nets(self):
        for n in networks:
            self._create_network(n)

    def _delete_nets(self):
        for n in networks:
            ctx = context.RequestContext('user1', n['project_id'])
            self.net_man.delete_network(ctx, None, n['uuid'])
        self.assertRaises(exception.NoNetworksFound,
                          db.network_get_all, ctx.elevated())

    def _validate_nw_info(self, nw_info, expected_net_labels):

        self.assertEquals(len(nw_info), len(expected_net_labels))

        ctx = context.RequestContext('user1', 'foo').elevated()
        all_net_map = {}
        for n in db.network_get_all(ctx):
            all_net_map[n['label']] = n

        for i in range(0, len(nw_info)):
            vif = nw_info[i]
            net = all_net_map[expected_net_labels[i]]

            # simple test assumes that each starting prefix is unique
            expected_v4_cidr_start = net['cidr'].split(".")[0].lower()
            expected_v6_cidr_start = net['cidr_v6'].split(":")[0].lower()

            for subnet in vif['network']['subnets']:
                addr = subnet['ips'][0]['address']
                if subnet['version'] == 4:
                    address_start = addr.split(".")[0].lower()
                    self.assertTrue(expected_v4_cidr_start, address_start)
                else:
                    address_start = addr.split(":")[0].lower()
                    self.assertTrue(expected_v6_cidr_start, address_start)

        # confirm that there is a DHCP device on corresponding net
        for l in expected_net_labels:
            n = all_net_map[l]
            tenant_id = (n['project_id'] or
                                FLAGS.quantum_default_tenant_id)
            ports = self.net_man.q_conn.get_attached_ports(
                                                    tenant_id, n['uuid'])
            self.assertEquals(len(ports), 2)  # gw + instance VIF

            # make sure we aren't allowed to delete network with
            # active port
            self.assertRaises(exception.NetworkBusy,
                              self.net_man.delete_network,
                              ctx, None, n['uuid'])

    def _check_vifs(self, expect_num_vifs):
        ctx = context.RequestContext('user1', "").elevated()
        self.assertEqual(len(db.virtual_interface_get_all(ctx)),
                        expect_num_vifs)

    def _allocate_and_deallocate_instance(self, project_id, requested_networks,
                                            expected_labels):

        ctx = context.RequestContext('user1', project_id)
        self._check_vifs(0)

        instance_ref = db.instance_create(ctx,
                                    {"project_id": project_id})

        nw_info = self.net_man.allocate_for_instance(ctx.elevated(),
                        instance_id=instance_ref['id'], host="",
                        rxtx_factor=3,
                        project_id=project_id,
                        requested_networks=requested_networks)

        self._check_vifs(len(nw_info))

        self._validate_nw_info(nw_info, expected_labels)

        nw_info = self.net_man.get_instance_nw_info(ctx, instance_ref['id'],
                                instance_ref['uuid'],
                                instance_ref['instance_type_id'], "",
                                project_id=project_id)

        self._check_vifs(len(nw_info))
        self._validate_nw_info(nw_info, expected_labels)

        port_net_pairs = []
        for vif in nw_info:
            nid = vif['network']['id']
            pid = self.net_man.q_conn.get_port_by_attachment(
                                project_id, nid, vif['id'])
            if pid is None:
                pid = self.net_man.q_conn.get_port_by_attachment(
                                FLAGS.quantum_default_tenant_id,
                                nid, vif['id'])
            self.assertTrue(pid is not None)
            port_net_pairs.append((pid, nid))

        self.net_man.deallocate_for_instance(ctx,
                    instance_id=instance_ref['id'],
                    project_id=project_id)

        for pid, nid in port_net_pairs:
            self.assertRaises(quantum_client.QuantumNotFoundException,
                            self.net_man.q_conn.detach_and_delete_port,
                            project_id, nid, pid)
            self.assertRaises(quantum_client.QuantumNotFoundException,
                            self.net_man.q_conn.detach_and_delete_port,
                            FLAGS.quantum_default_tenant_id, nid, pid)

        self._check_vifs(0)

    def test_allocate_and_deallocate_instance_static(self):
        self._create_nets()
        self._allocate_and_deallocate_instance("fake_project1", None,
                                 ['public', 'project1-net1'])
        self._delete_nets()

    def test_allocate_and_deallocate_instance_dynamic(self):

        self._create_nets()
        project_id = "fake_project2"
        ctx = context.RequestContext('user1', project_id)
        all_valid_networks = self.net_man.ipam.get_project_and_global_net_ids(
                                                               ctx, project_id)
        requested_networks = [(n[0], None) for n in all_valid_networks]

        self.net_man.validate_networks(ctx, requested_networks)

        label_map = {}
        for n in db.network_get_all(ctx.elevated()):
            label_map[n['uuid']] = n['label']
        expected_labels = [label_map[uid] for uid, _i in requested_networks]

        self._allocate_and_deallocate_instance(project_id, requested_networks,
                                              expected_labels)
        self._delete_nets()

    def test_validate_bad_network(self):
        ctx = context.RequestContext('user1', 'fake_project1')
        self.assertRaises(exception.NetworkNotFound,
                        self.net_man.validate_networks, ctx, [("", None)])

    def test_create_net_external_uuid(self):
        """Tests use case where network can be created directly via
           Quantum API, then the UUID is passed in via nova-manage"""
        project_id = "foo_project"
        ctx = context.RequestContext('user1', project_id)
        net_id = self.net_man.q_conn.create_network(project_id, 'net1')
        self.net_man.create_networks(
            ctx,
            label='achtungbaby',
            cidr="9.9.9.0/24",
            multi_host=False,
            num_networks=1,
            network_size=256,
            cidr_v6=None,
            gateway="9.9.9.1",
            gateway_v6=None,
            bridge=None,
            bridge_interface=None,
            dns1="8.8.8.8",
            project_id=project_id,
            priority=9,
            uuid=net_id)
        net = db.network_get_by_uuid(ctx.elevated(), net_id)
        self.assertTrue(net is not None)
        self.assertEquals(net['uuid'], net_id)

    def test_create_net_external_uuid_and_host_is_set(self):
        """Make sure network['host'] is set when creating a network via the
           network manager"""
        project_id = "foo_project"
        ctx = context.RequestContext('user1', project_id)
        net_id = self.net_man.q_conn.create_network(project_id, 'net2')
        self.net_man.create_networks(
            ctx, label='achtungbaby2', cidr="9.9.8.0/24", multi_host=False,
            num_networks=1, network_size=256, cidr_v6=None,
            gateway="9.9.8.1", gateway_v6=None, bridge=None,
            bridge_interface=None, dns1="8.8.8.8", project_id=project_id,
            priority=8, uuid=net_id)
        net = db.network_get_by_uuid(ctx.elevated(), net_id)
        self.assertTrue(net is not None)
        self.assertEquals(net['uuid'], net_id)
        self.assertTrue(net['host'] != None)


class QuantumNovaMACGenerationTestCase(QuantumNovaTestCase):
    def test_local_mac_address_creation(self):
        self.flags(use_melange_mac_generation=False)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(utils, "generate_mac_address",
                       lambda: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        all_valid_networks = self.net_man.ipam.get_project_and_global_net_ids(
                                                               ctx, project_id)
        requested_networks = [(n[0], None) for n in all_valid_networks]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        rxtx_factor=3,
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0]['address'], fake_mac)

    def test_melange_mac_address_creation(self):
        self.flags(use_melange_mac_generation=True)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(melange_connection.MelangeConnection, "create_vif",
                       lambda w, x, y, z: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        all_valid_networks = self.net_man.ipam.get_project_and_global_net_ids(
                                                               ctx, project_id)
        requested_networks = [(n[0], None) for n in all_valid_networks]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        rxtx_factor=3,
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0]['address'], fake_mac)


class QuantumNovaPortSecurityTestCase(QuantumNovaTestCase):
    def test_port_securty(self):
        self.flags(use_melange_mac_generation=True)
        self.flags(quantum_use_port_security=True)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(melange_connection.MelangeConnection, "create_vif",
                       lambda w, x, y, z: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        all_valid_networks = self.net_man.ipam.get_project_and_global_net_ids(
                                                               ctx, project_id)
        requested_networks = [(n[0], None) for n in all_valid_networks]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        oldfunc = self.net_man.q_conn.create_and_attach_port

        # Make sure we get the appropriate mac set in allowed_address_pairs
        # if port security is enabled.
        def _instrumented_create_and_attach_port(tenant_id, net_id,
                                                 interface_id, **kwargs):
            self.assertTrue('allowed_address_pairs' in kwargs.keys())
            pairs = kwargs['allowed_address_pairs']
            self.assertTrue(pairs[0]['mac_address'] == fake_mac)
            self.net_man.q_conn.create_and_attach_port = oldfunc
            return oldfunc(tenant_id, net_id, interface_id, **kwargs)
        _port_attach = _instrumented_create_and_attach_port
        self.net_man.q_conn.create_and_attach_port = _port_attach
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        rxtx_factor=3,
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0]['address'], fake_mac)

    def test_port_securty_negative(self):
        self.flags(use_melange_mac_generation=True)
        self.flags(quantum_use_port_security=False)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(melange_connection.MelangeConnection, "create_vif",
                       lambda w, x, y, z: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        all_valid_networks = self.net_man.ipam.get_project_and_global_net_ids(
                                                               ctx, project_id)
        requested_networks = [(n[0], None) for n in all_valid_networks]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        oldfunc = self.net_man.q_conn.create_and_attach_port

        # Make sure no pairs are passed in if port security is turned off
        def _instrumented_create_and_attach_port(tenant_id, net_id,
                                                 interface_id, **kwargs):
            self.assertTrue('allowed_address_pairs' in kwargs.keys())
            pairs = kwargs['allowed_address_pairs']
            self.assertTrue(len(pairs) == 0)
            self.net_man.q_conn.create_and_attach_port = oldfunc
            return oldfunc(tenant_id, net_id, interface_id, **kwargs)
        _port_attach = _instrumented_create_and_attach_port
        self.net_man.q_conn.create_and_attach_port = _port_attach
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        rxtx_factor=3,
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0]['address'], fake_mac)
