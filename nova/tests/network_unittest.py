# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import IPy
import os
import logging

from nova import flags
from nova import test
from nova import utils
from nova.auth import manager
from nova.network import model
from nova.network import service
from nova.network.exception import NoMoreAddresses

FLAGS = flags.FLAGS

class NetworkTestCase(test.TrialTestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        # NOTE(vish): if you change these flags, make sure to change the
        #             flags in the corresponding section in nova-dhcpbridge
        self.flags(connection_type='fake',
                   fake_storage=True,
                   fake_network=True,
                   auth_driver='nova.auth.ldapdriver.FakeLdapDriver',
                   network_size=32)
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = manager.AuthManager()
        self.dnsmasq = FakeDNSMasq()
        self.user = self.manager.create_user('netuser', 'netuser', 'netuser')
        self.projects = []
        self.projects.append(self.manager.create_project('netuser',
                                                         'netuser',
                                                         'netuser'))
        for i in range(0, 6):
            name = 'project%s' % i
            self.projects.append(self.manager.create_project(name,
                                                             'netuser',
                                                             name))
        self.network = model.PublicNetworkController()
        self.service = service.VlanNetworkService()

    def tearDown(self):
        super(NetworkTestCase, self).tearDown()
        for project in self.projects:
            self.manager.delete_project(project)
        self.manager.delete_user(self.user)

    def test_public_network_allocation(self):
        pubnet = IPy.IP(flags.FLAGS.public_range)
        address = self.network.allocate_ip(self.user.id, self.projects[0].id, "public")
        self.assertTrue(IPy.IP(address) in pubnet)
        self.assertTrue(IPy.IP(address) in self.network.network)

    def test_allocate_deallocate_fixed_ip(self):
        result  = self.service.allocate_fixed_ip(
                self.user.id, self.projects[0].id)
        address = result['ip']
        mac = result['mac']
        logging.debug("Was allocated %s" % (address))
        net = model.get_project_network(self.projects[0].id, "default")
        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        hostname = "test-host"
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        rv = self.service.deallocate_fixed_ip(address)

        # Doesn't go away until it's dhcp released
        self.assertEqual(True, is_in_project(address, self.projects[0].id))

        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

    def test_range_allocation(self):
        hostname = "test-host"
        result = self.service.allocate_fixed_ip(
                    self.user.id, self.projects[0].id)
        mac = result['mac']
        address = result['ip']
        result = self.service.allocate_fixed_ip(
                self.user, self.projects[1].id)
        secondmac = result['mac']
        secondaddress = result['ip']

        net = model.get_project_network(self.projects[0].id, "default")
        secondnet = model.get_project_network(self.projects[1].id, "default")

        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        self.assertEqual(True, is_in_project(secondaddress, self.projects[1].id))
        self.assertEqual(False, is_in_project(address, self.projects[1].id))

        # Addresses are allocated before they're issued
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        self.dnsmasq.issue_ip(secondmac, secondaddress,
                                hostname, secondnet.bridge_name)

        rv = self.service.deallocate_fixed_ip(address)
        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertEqual(True, is_in_project(secondaddress, self.projects[1].id))

        rv = self.service.deallocate_fixed_ip(secondaddress)
        self.dnsmasq.release_ip(secondmac, secondaddress,
                                hostname, secondnet.bridge_name)
        self.assertEqual(False, is_in_project(secondaddress, self.projects[1].id))

    def test_subnet_edge(self):
        result = self.service.allocate_fixed_ip(self.user.id,
                                                       self.projects[0].id)
        firstaddress = result['ip']
        hostname = "toomany-hosts"
        for i in range(1,5):
            project_id = self.projects[i].id
            result = self.service.allocate_fixed_ip(
                    self.user, project_id)
            mac = result['mac']
            address = result['ip']
            result = self.service.allocate_fixed_ip(
                    self.user, project_id)
            mac2 = result['mac']
            address2 = result['ip']
            result = self.service.allocate_fixed_ip(
                   self.user, project_id)
            mac3 = result['mac']
            address3 = result['ip']
            self.assertEqual(False, is_in_project(address, self.projects[0].id))
            self.assertEqual(False, is_in_project(address2, self.projects[0].id))
            self.assertEqual(False, is_in_project(address3, self.projects[0].id))
            rv = self.service.deallocate_fixed_ip(address)
            rv = self.service.deallocate_fixed_ip(address2)
            rv = self.service.deallocate_fixed_ip(address3)
            net = model.get_project_network(project_id, "default")
            self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac2, address2, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac3, address3, hostname, net.bridge_name)
        net = model.get_project_network(self.projects[0].id, "default")
        rv = self.service.deallocate_fixed_ip(firstaddress)
        self.dnsmasq.release_ip(mac, firstaddress, hostname, net.bridge_name)

    def test_release_before_deallocate(self):
        pass

    def test_deallocate_before_issued(self):
        pass

    def test_too_many_addresses(self):
        """
        Here, we test that a proper NoMoreAddresses exception is raised.

        However, the number of available IP addresses depends on the test
        environment's setup.

        Network size is set in test fixture's setUp method.

        There are FLAGS.cnt_vpn_clients addresses reserved for VPN (NUM_RESERVED_VPN_IPS)

        And there are NUM_STATIC_IPS that are always reserved by Nova for the necessary
        services (gateway, CloudPipe, etc)

        So we should get flags.network_size - (NUM_STATIC_IPS +
                                               NUM_PREALLOCATED_IPS +
                                               NUM_RESERVED_VPN_IPS)
        usable addresses
        """
        net = model.get_project_network(self.projects[0].id, "default")

        # Determine expected number of available IP addresses
        num_static_ips = net.num_static_ips
        num_preallocated_ips = len(net.hosts.keys())
        num_reserved_vpn_ips = flags.FLAGS.cnt_vpn_clients
        num_available_ips = flags.FLAGS.network_size - (num_static_ips +
                                                        num_preallocated_ips +
                                                        num_reserved_vpn_ips)

        hostname = "toomany-hosts"
        macs = {}
        addresses = {}
        for i in range(0, (num_available_ips - 1)):
            result = self.service.allocate_fixed_ip(self.user.id, self.projects[0].id)
            macs[i] = result['mac']
            addresses[i] = result['ip']
            self.dnsmasq.issue_ip(macs[i], addresses[i], hostname, net.bridge_name)

        self.assertRaises(NoMoreAddresses, self.service.allocate_fixed_ip, self.user.id, self.projects[0].id)

        for i in range(0, (num_available_ips - 1)):
            rv = self.service.deallocate_fixed_ip(addresses[i])
            self.dnsmasq.release_ip(macs[i], addresses[i], hostname, net.bridge_name)

def is_in_project(address, project_id):
    return address in model.get_project_network(project_id).list_addresses()

def _get_project_addresses(project_id):
    project_addresses = []
    for addr in model.get_project_network(project_id).list_addresses():
        project_addresses.append(addr)
    return project_addresses

def binpath(script):
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))

class FakeDNSMasq(object):
    def issue_ip(self, mac, ip, hostname, interface):
        cmd = "%s add %s %s %s" % (binpath('nova-dhcpbridge'),
                                   mac, ip, hostname)
        env = {'DNSMASQ_INTERFACE': interface,
               'TESTING' : '1',
               'FLAGFILE' : FLAGS.dhcpbridge_flagfile}
        (out, err) = utils.execute(cmd, addl_env=env)
        logging.debug("ISSUE_IP: %s, %s " % (out, err))

    def release_ip(self, mac, ip, hostname, interface):
        cmd = "%s del %s %s %s" % (binpath('nova-dhcpbridge'),
                                   mac, ip, hostname)
        env = {'DNSMASQ_INTERFACE': interface,
               'TESTING' : '1',
               'FLAGFILE' : FLAGS.dhcpbridge_flagfile}
        (out, err) = utils.execute(cmd, addl_env=env)
        logging.debug("RELEASE_IP: %s, %s " % (out, err))

