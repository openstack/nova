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
from nova import exception
from nova import log as logging
from nova import test
from nova.network.quantum import manager as quantum_manager

LOG = logging.getLogger('nova.tests.quantum_network')

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
class QuantumTestCaseBase(object):

    def test_create_and_delete_nets(self):
        self._create_nets()
        self._delete_nets()

    def _create_nets(self):
        for n in networks:
            ctx = context.RequestContext('user1', n['project_id'])
            self.net_man.create_networks(ctx,
                    label=n['label'], cidr=n['cidr'],
                    multi_host=n['multi_host'],
                    num_networks=1, network_size=256, cidr_v6=n['cidr_v6'],
                    gateway_v6=n['gateway_v6'], bridge=None,
                    bridge_interface=None, dns1=n['dns1'],
                    dns2=n['dns2'], project_id=n['project_id'],
                    priority=n['priority'])

    def _delete_nets(self):
        for n in networks:
            ctx = context.RequestContext('user1', n['project_id'])
            self.net_man.delete_network(ctx, n['cidr'])

    def test_allocate_and_deallocate_instance_static(self):
        self._create_nets()

        project_id = "fake_project1"
        ctx = context.RequestContext('user1', project_id)

        instance_ref = db.api.instance_create(ctx, {})
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
        self.assertTrue(\
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1dba:"))
        self.assertTrue(\
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
        requested_networks = [(net_id, None) for net_id in net_ids]

        self.net_man.validate_networks(ctx, requested_networks)

        instance_ref = db.api.instance_create(ctx, {})
        nw_info = self.net_man.allocate_for_instance(ctx,
                        instance_id=instance_ref['id'], host="",
                        instance_type_id=instance_ref['instance_type_id'],
                        project_id=project_id,
                        requested_networks=requested_networks)

        self.assertEquals(len(nw_info), 2)

        # we don't know which order the NICs will be in until we
        # introduce the notion of priority
        # v4 cidr
        self.assertTrue(nw_info[0][0]['cidr'].startswith("9.") or \
                        nw_info[1][0]['cidr'].startswith("9."))
        self.assertTrue(nw_info[0][0]['cidr'].startswith("192.") or \
                        nw_info[1][0]['cidr'].startswith("192."))

        # v4 address
        self.assertTrue(nw_info[0][1]['ips'][0]['ip'].startswith("9.") or \
                        nw_info[1][1]['ips'][0]['ip'].startswith("9."))
        self.assertTrue(nw_info[0][1]['ips'][0]['ip'].startswith("192.") or \
                        nw_info[1][1]['ips'][0]['ip'].startswith("192."))

        # v6 cidr
        self.assertTrue(nw_info[0][0]['cidr_v6'].startswith("2001:1dbb:") or \
                        nw_info[1][0]['cidr_v6'].startswith("2001:1dbb:"))
        self.assertTrue(nw_info[0][0]['cidr_v6'].startswith("2001:1db9:") or \
                        nw_info[1][0]['cidr_v6'].startswith("2001:1db9:"))

        # v6 address
        self.assertTrue(\
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1dbb:") or \
            nw_info[1][1]['ip6s'][0]['ip'].startswith("2001:1dbb:"))
        self.assertTrue(\
            nw_info[0][1]['ip6s'][0]['ip'].startswith("2001:1db9:") or \
            nw_info[1][1]['ip6s'][0]['ip'].startswith("2001:1db9:"))

        self.net_man.deallocate_for_instance(ctx,
                    instance_id=instance_ref['id'],
                    project_id=project_id)

        self._delete_nets()

    def test_validate_bad_network(self):
        ctx = context.RequestContext('user1', 'fake_project1')
        self.assertRaises(exception.NetworkNotFound,
                        self.net_man.validate_networks, ctx, [("", None)])


class QuantumFakeIPAMTestCase(QuantumTestCaseBase, test.TestCase):

    def setUp(self):
        super(QuantumFakeIPAMTestCase, self).setUp()
        self.net_man = quantum_manager.QuantumManager( \
                ipam_lib="nova.network.quantum.fake")


class QuantumNovaIPAMTestCase(QuantumTestCaseBase, test.TestCase):

    def setUp(self):
        super(QuantumNovaIPAMTestCase, self).setUp()
        self.net_man = quantum_manager.QuantumManager( \
                ipam_lib="nova.network.quantum.nova_ipam_lib")

        # tests seem to create some networks by default, which
        # don't want.  So we delete them.

        ctx = context.RequestContext('user1', 'fake_project1').elevated()
        for n in db.network_get_all(ctx):
            db.network_delete_safe(ctx, n['id'])

# Cannot run this unit tests auotmatically for now, as it requires
# melange to be running locally.
#
#class QuantumMelangeIPAMTestCase(QuantumTestCaseBase, test.TestCase):
#
#    def setUp(self):
#        super(QuantumMelangeIPAMTestCase, self).setUp()
#        self.net_man = quantum_manager.QuantumManager( \
#                ipam_lib="nova.network.quantum.melange_ipam_lib")
