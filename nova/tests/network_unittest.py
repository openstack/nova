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
from nova.compute import network
from nova.compute.exception import NoMoreAddresses

FLAGS = flags.FLAGS

class NetworkTestCase(test.TrialTestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        # NOTE(vish): if you change these flags, make sure to change the
        #             flags in the corresponding section in nova-dhcpbridge
        self.flags(fake_libvirt=True,
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
        self.network = network.PublicNetworkController()

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

    def test_allocate_deallocate_ip(self):
        address = network.allocate_ip(
                self.user.id, self.projects[0].id, utils.generate_mac())
        logging.debug("Was allocated %s" % (address))
        net = network.get_project_network(self.projects[0].id, "default")
        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        mac = utils.generate_mac()
        hostname = "test-host"
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        rv = network.deallocate_ip(address)

        # Doesn't go away until it's dhcp released
        self.assertEqual(True, is_in_project(address, self.projects[0].id))

        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

    def test_range_allocation(self):
        mac = utils.generate_mac()
        secondmac = utils.generate_mac()
        hostname = "test-host"
        address = network.allocate_ip(
                    self.user.id, self.projects[0].id, mac)
        secondaddress = network.allocate_ip(
                self.user, self.projects[1].id, secondmac)
        net = network.get_project_network(self.projects[0].id, "default")
        secondnet = network.get_project_network(self.projects[1].id, "default")

        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        self.assertEqual(True, is_in_project(secondaddress, self.projects[1].id))
        self.assertEqual(False, is_in_project(address, self.projects[1].id))

        # Addresses are allocated before they're issued
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        self.dnsmasq.issue_ip(secondmac, secondaddress,
                                hostname, secondnet.bridge_name)

        rv = network.deallocate_ip(address)
        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertEqual(True, is_in_project(secondaddress, self.projects[1].id))

        rv = network.deallocate_ip(secondaddress)
        self.dnsmasq.release_ip(secondmac, secondaddress,
                                hostname, secondnet.bridge_name)
        self.assertEqual(False, is_in_project(secondaddress, self.projects[1].id))

    def test_subnet_edge(self):
        secondaddress = network.allocate_ip(self.user.id, self.projects[0].id,
                                utils.generate_mac())
        hostname = "toomany-hosts"
        for i in range(1,5):
            project_id = self.projects[i].id
            mac = utils.generate_mac()
            mac2 = utils.generate_mac()
            mac3 = utils.generate_mac()
            address = network.allocate_ip(
                    self.user, project_id, mac)
            address2 = network.allocate_ip(
                    self.user, project_id, mac2)
            address3 = network.allocate_ip(
                    self.user, project_id, mac3)
            self.assertEqual(False, is_in_project(address, self.projects[0].id))
            self.assertEqual(False, is_in_project(address2, self.projects[0].id))
            self.assertEqual(False, is_in_project(address3, self.projects[0].id))
            rv = network.deallocate_ip(address)
            rv = network.deallocate_ip(address2)
            rv = network.deallocate_ip(address3)
            net = network.get_project_network(project_id, "default")
            self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac2, address2, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac3, address3, hostname, net.bridge_name)
        net = network.get_project_network(self.projects[0].id, "default")
        rv = network.deallocate_ip(secondaddress)
        self.dnsmasq.release_ip(mac, secondaddress, hostname, net.bridge_name)

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
        net = network.get_project_network(self.projects[0].id, "default")

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
            macs[i] = utils.generate_mac()
            addresses[i] = network.allocate_ip(self.user.id, self.projects[0].id, macs[i])
            self.dnsmasq.issue_ip(macs[i], addresses[i], hostname, net.bridge_name)

        self.assertRaises(NoMoreAddresses, network.allocate_ip, self.user.id, self.projects[0].id, utils.generate_mac())

        for i in range(0, (num_available_ips - 1)):
            rv = network.deallocate_ip(addresses[i])
            self.dnsmasq.release_ip(macs[i], addresses[i], hostname, net.bridge_name)

def is_in_project(address, project_id):
    return address in network.get_project_network(project_id).list_addresses()

def _get_project_addresses(project_id):
    project_addresses = []
    for addr in network.get_project_network(project_id).list_addresses():
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

