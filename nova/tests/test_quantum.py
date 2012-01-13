# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Nicira, Inc.
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

from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from nova import exception
from nova import log as logging
from nova.network.quantum import manager as quantum_manager
from nova.network.quantum import melange_connection
from nova import test
from nova import utils
from nova.network import manager

LOG = logging.getLogger('nova.tests.quantum_network')


# this class can be used for unit functional/testing on nova,
# as it does not actually make remote calls to the Quantum service
class FakeQuantumClientConnection(object):

    def __init__(self):
        self.nets = {}

    def get_networks_for_tenant(self, tenant_id):
        net_ids = []
        for net_id, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                net_ids.append(net_id)
        return {'networks': net_ids}

    def create_network(self, tenant_id, network_name, **kwargs):

        uuid = str(utils.gen_uuid())
        self.nets[uuid] = {'net-name': network_name,
                           'tenant-id': tenant_id,
                           'ports': {}}
        return uuid

    def delete_network(self, tenant_id, net_id):
        if self.nets[net_id]['tenant-id'] == tenant_id:
            del self.nets[net_id]

    def network_exists(self, tenant_id, net_id):
        try:
            return self.nets[net_id]['tenant-id'] == tenant_id
        except KeyError:
            return False

    def get_network_name(self, tenant_id, net_id):
        return self.nets[net_id]['net-name']

    def _confirm_not_attached(self, interface_id):
        for n in self.nets.values():
            for p in n['ports'].values():
                if p['attachment-id'] == interface_id:
                    raise Exception(_("interface '%s' is already attached" %
                                          interface_id))

    def create_and_attach_port(self, tenant_id, net_id, interface_id,
                               **kwargs):
        if not self.network_exists(tenant_id, net_id):
            raise Exception(
                _("network %(net_id)s does not exist for tenant %(tenant_id)"
                    % locals()))

        self._confirm_not_attached(interface_id)
        uuid = str(utils.gen_uuid())
        self.nets[net_id]['ports'][uuid] = \
                {"port-state": "ACTIVE",
                "attachment-id": interface_id}

    def detach_and_delete_port(self, tenant_id, net_id, port_id):
        if not self.network_exists(tenant_id, net_id):
            raise exception.NotFound(
                    _("network %(net_id)s does not exist "
                        "for tenant %(tenant_id)s" % locals()))
        del self.nets[net_id]['ports'][port_id]

    def get_port_by_attachment(self, tenant_id, net_id, attachment_id):
        for nid, n in self.nets.items():
            if nid == net_id and n['tenant-id'] == tenant_id:
                for port_id, p in n['ports'].items():
                    if p['attachment-id'] == attachment_id:
                        return port_id
        return None

    def get_attached_ports(self, tenant_id, net_id):
        ports = []
        for nid, n in self.nets.items():
            if nid == net_id and n['tenant-id'] == tenant_id:
                for port_id, p in n['ports'].items():
                    ports.append({'port-id': port_id,
                            'attachment': p['attachment-id']})
        return ports

    def get_networks(self, tenant_id):
        nets = []
        for nid, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                x = {'id': nid}
                nets.append(x)
        return {'networks': nets}


networks = [{'label': 'project1-net1',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.0.0/24',
             'cidr_v6': '2001:1db8::/64',
             'gateway_v6': '2001:1db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': None,
             'vpn_public_address': None,
             'project_id': 'fake_project1',
             'priority': 1},
            {'label': 'project2-net1',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.1.0/24',
             'cidr_v6': '2001:1db9::/64',
             'gateway_v6': '2001:1db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project2',
             'priority': 1},
             {'label': "public",
             'injected': False,
             'multi_host': False,
             'cidr': '10.0.0.0/24',
             'cidr_v6': '2001:1dba::/64',
             'gateway_v6': '2001:1dba::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '10.0.0.1',
             'broadcast': '10.0.0.255',
             'dns1': '10.0.0.1',
             'dns2': '10.0.0.2',
             'vlan': None,
             'host': None,
             'project_id': None,
             'priority': 0},
             {'label': "project2-net2",
             'injected': False,
             'multi_host': False,
             'cidr': '9.0.0.0/24',
             'cidr_v6': '2001:1dbb::/64',
             'gateway_v6': '2001:1dbb::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': None,
             'bridge_interface': None,
             'gateway': '9.0.0.1',
             'broadcast': '9.0.0.255',
             'dns1': '9.0.0.1',
             'dns2': '9.0.0.2',
             'vlan': None,
             'host': None,
             'project_id': "fake_project2",
             'priority': 2}]


# this is a base class to be used by all other Quantum Test classes
class QuantumNovaTestCase(test.TestCase):
    def setUp(self):
        super(QuantumNovaTestCase, self).setUp()

        self.net_man = quantum_manager.QuantumManager(
                ipam_lib="nova.network.quantum.nova_ipam_lib",
                q_conn=FakeQuantumClientConnection())

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
            dns2=n['dns2'],
            project_id=n['project_id'],
            priority=n['priority'])
        n['uuid'] = nwks[0]['uuid']


class QuantumNovaIPAMTestCase(QuantumNovaTestCase):
    def test_create_and_delete_nets(self):
        self._create_nets()
        self._delete_nets()

    def _create_nets(self):
        for n in networks:
            self._create_network(n)

    def _delete_nets(self):
        for n in networks:
            ctx = context.RequestContext('user1', n['project_id'])
            db_nets = db.network_get_all(ctx.elevated())
            for x in db_nets:
                if x['label'] == n['label']:
                    n['uuid'] = x['uuid']
            self.net_man.delete_network(ctx, None, n['uuid'])

    def test_allocate_and_deallocate_instance_static(self):
        self._create_nets()

        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)

        instance_ref = db.instance_create(ctx,
                                    {"project_id": project_id})

        def func(arg1, arg2):
            pass

        def func2(arg1, arg2, arg3):
            pass

        def func1(arg1):
            pass

        self.net_man.driver.update_dhcp_hostfile_with_text = func
        self.net_man.driver.restart_dhcp = func2
        self.net_man.driver.kill_dhcp = func1
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        instance_type_id=instance_ref['instance_type_id'],
                        project_id=project_id)

        self.assertEquals(len(nw_info), 2)

        # we don't know which order the NICs will be in until we
        # introduce the notion of priority
        # v4 cidr
        self.assertTrue(nw_info[0][0]['cidr'].startswith("10."))
        self.assertTrue(nw_info[1][0]['cidr'].startswith("192."))

        # v4 address
        self.assertTrue(nw_info[0][1]['ips'][0]['ip'].startswith("10."))
        self.assertTrue(nw_info[1][1]['ips'][0]['ip'].startswith("192."))

        # v6 cidr
        self.assertTrue(nw_info[0][0]['cidr_v6'].startswith("2001:1dba:"))
        self.assertTrue(nw_info[1][0]['cidr_v6'].startswith("2001:1db8:"))

        # v6 address
        self.assertTrue(
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1dba:"))
        self.assertTrue(
            nw_info[1][1]['ip6s'][0]['ip'].startswith("2001:1db8:"))

        self.net_man.deallocate_for_instance(ctx,
                    instance_id=instance_ref['id'],
                    project_id=project_id)

        self._delete_nets()

    def test_allocate_and_deallocate_instance_dynamic(self):
        self._create_nets()
        project_id = "fake_project2"
        ctx = context.RequestContext('user1', project_id)

        net_ids = self.net_man.q_conn.get_networks_for_tenant(project_id)
        requested_networks = [(net_id, None) for net_id in
            net_ids['networks']]

        self.net_man.validate_networks(ctx, requested_networks)

        instance_ref = db.instance_create(ctx,
                                    {"project_id": project_id})

        def func(arg1, arg2):
            pass

        def func1(arg1):
            pass

        def func2(arg1, arg2, arg3):
            pass

        self.net_man.driver.update_dhcp_hostfile_with_text = func
        self.net_man.driver.restart_dhcp = func2
        self.net_man.driver.kill_dhcp = func1
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        instance_type_id=instance_ref['instance_type_id'],
                        project_id=project_id,
                        requested_networks=requested_networks)

        self.assertEquals(len(nw_info), 2)

        # we don't know which order the NICs will be in until we
        # introduce the notion of priority
        # v4 cidr
        self.assertTrue(nw_info[0][0]['cidr'].startswith("9.") or
                        nw_info[1][0]['cidr'].startswith("9."))
        self.assertTrue(nw_info[0][0]['cidr'].startswith("192.") or
                        nw_info[1][0]['cidr'].startswith("192."))

        # v4 address
        self.assertTrue(nw_info[0][1]['ips'][0]['ip'].startswith("9.") or
                        nw_info[1][1]['ips'][0]['ip'].startswith("9."))
        self.assertTrue(nw_info[0][1]['ips'][0]['ip'].startswith("192.") or
                        nw_info[1][1]['ips'][0]['ip'].startswith("192."))

        # v6 cidr
        self.assertTrue(nw_info[0][0]['cidr_v6'].startswith("2001:1dbb:") or
                        nw_info[1][0]['cidr_v6'].startswith("2001:1dbb:"))
        self.assertTrue(nw_info[0][0]['cidr_v6'].startswith("2001:1db9:") or
                        nw_info[1][0]['cidr_v6'].startswith("2001:1db9:"))

        # v6 address
        self.assertTrue(
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1dbb:") or
            nw_info[1][1]['ip6s'][0]['ip'].startswith("2001:1dbb:"))
        self.assertTrue(
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1db9:") or
            nw_info[1][1]['ip6s'][0]['ip'].startswith("2001:1db9:"))

        self.net_man.deallocate_for_instance(ctx,
                    instance_id=instance_ref['id'],
                    project_id=project_id)

        self._delete_nets()

    def test_validate_bad_network(self):
        ctx = context.RequestContext('user1', 'fake_project1')
        self.assertRaises(exception.NetworkNotFound,
                        self.net_man.validate_networks, ctx, [("", None)])


class QuantumNovaMACGenerationTestCase(QuantumNovaTestCase):
    def test_local_mac_address_creation(self):
        self.flags(use_melange_mac_generation=False)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(manager.FlatManager, "generate_mac_address",
                       lambda x: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        net_ids = self.net_man.q_conn.get_networks_for_tenant(project_id)
        requested_networks = [(net_id, None) for net_id in net_ids['networks']]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        instance_type_id=instance_ref['instance_type_id'],
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0][1]['mac'], fake_mac)

    def test_melange_mac_address_creation(self):
        self.flags(use_melange_mac_generation=True)
        fake_mac = "ab:cd:ef:ab:cd:ef"
        self.stubs.Set(melange_connection.MelangeConnection, "create_vif",
                       lambda w, x, y, z: fake_mac)
        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)
        self._create_network(networks[0])

        net_ids = self.net_man.q_conn.get_networks_for_tenant(project_id)
        requested_networks = [(net_id, None) for net_id in net_ids['networks']]

        instance_ref = db.api.instance_create(ctx,
                                    {"project_id": project_id})
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        instance_type_id=instance_ref['instance_type_id'],
                        project_id=project_id,
                        requested_networks=requested_networks)
        self.assertEqual(nw_info[0][1]['mac'], fake_mac)
