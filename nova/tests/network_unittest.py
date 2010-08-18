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
"""
Unit Tests for network code
"""
import IPy
import os
import logging

from nova import flags
from nova import models
from nova import test
from nova import utils
from nova.auth import manager
from nova.network import service
from nova.network.exception import NoMoreAddresses

FLAGS = flags.FLAGS


class NetworkTestCase(test.TrialTestCase):
    """Test cases for network code"""
    def setUp(self):  # pylint: disable=C0103
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
        self.user = self.manager.create_user('netuser', 'netuser', 'netuser')
        self.projects = []
        self.service = service.VlanNetworkService()
        for i in range(0, 6):
            name = 'project%s' % i
            self.projects.append(self.manager.create_project(name,
                                                             'netuser',
                                                             name))
            # create the necessary network data for the project
            self.service.set_network_host(self.projects[i].id)
        instance = models.Instance()
        instance.mac_address = utils.generate_mac()
        instance.hostname = 'fake'
        instance.image_id = 'fake'
        instance.save()
        self.instance = instance

    def tearDown(self):  # pylint: disable=C0103
        super(NetworkTestCase, self).tearDown()
        for project in self.projects:
            self.manager.delete_project(project)
        self.manager.delete_user(self.user)

    def test_public_network_allocation(self):
        """Makes sure that we can allocaate a public ip"""
        pubnet = IPy.IP(flags.FLAGS.public_range)
        address = self.service.allocate_elastic_ip(self.projects[0].id)
        self.assertTrue(IPy.IP(address) in pubnet)

    def test_allocate_deallocate_fixed_ip(self):
        """Makes sure that we can allocate and deallocate a fixed ip"""
        address = self.service.allocate_fixed_ip(self.projects[0].id,
                                                 self.instance.id)
        net = service.get_project_network(self.projects[0].id)
        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        issue_ip(self.instance.mac_address,
                 address,
                 self.instance.hostname,
                 net.bridge)
        self.service.deallocate_fixed_ip(address)

        # Doesn't go away until it's dhcp released
        self.assertEqual(True, is_in_project(address, self.projects[0].id))

        release_ip(self.instance.mac_address,
                 address,
                 self.instance.hostname,
                 net.bridge)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

    def test_side_effects(self):
        """Ensures allocating and releasing has no side effects"""
        hostname = "side-effect-host"
        result = self.service.allocate_fixed_ip(
                                                self.projects[0].id)
        mac = result['mac_address']
        address = result['private_dns_name']
        result = self.service.allocate_fixed_ip(self.user,
                                                self.projects[1].id)
        secondmac = result['mac_address']
        secondaddress = result['private_dns_name']

        net = service.get_project_network(self.projects[0].id)
        secondnet = service.get_project_network(self.projects[1].id)

        self.assertEqual(True, is_in_project(address, self.projects[0].id))
        self.assertEqual(True, is_in_project(secondaddress,
                                             self.projects[1].id))
        self.assertEqual(False, is_in_project(address, self.projects[1].id))

        # Addresses are allocated before they're issued
        issue_ip(mac, address, hostname, net.bridge_name)
        issue_ip(secondmac, secondaddress, hostname, secondnet.bridge_name)

        self.service.deallocate_fixed_ip(address)
        release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertEqual(True, is_in_project(secondaddress,
                                             self.projects[1].id))

        self.service.deallocate_fixed_ip(secondaddress)
        release_ip(secondmac, secondaddress, hostname, secondnet.bridge_name)
        self.assertEqual(False, is_in_project(secondaddress,
                                              self.projects[1].id))

    def test_subnet_edge(self):
        """Makes sure that private ips don't overlap"""
        result = self.service.allocate_fixed_ip(
                                                       self.projects[0].id)
        firstaddress = result['private_dns_name']
        hostname = "toomany-hosts"
        for i in range(1, 5):
            project_id = self.projects[i].id
            result = self.service.allocate_fixed_ip(
                    self.user, project_id)
            mac = result['mac_address']
            address = result['private_dns_name']
            result = self.service.allocate_fixed_ip(
                    self.user, project_id)
            mac2 = result['mac_address']
            address2 = result['private_dns_name']
            result = self.service.allocate_fixed_ip(
                   self.user, project_id)
            mac3 = result['mac_address']
            address3 = result['private_dns_name']
            net = service.get_project_network(project_id)
            issue_ip(mac, address, hostname, net.bridge_name)
            issue_ip(mac2, address2, hostname, net.bridge_name)
            issue_ip(mac3, address3, hostname, net.bridge_name)
            self.assertEqual(False, is_in_project(address,
                                                  self.projects[0].id))
            self.assertEqual(False, is_in_project(address2,
                                                  self.projects[0].id))
            self.assertEqual(False, is_in_project(address3,
                                                  self.projects[0].id))
            self.service.deallocate_fixed_ip(address)
            self.service.deallocate_fixed_ip(address2)
            self.service.deallocate_fixed_ip(address3)
            release_ip(mac, address, hostname, net.bridge_name)
            release_ip(mac2, address2, hostname, net.bridge_name)
            release_ip(mac3, address3, hostname, net.bridge_name)
        net = service.get_project_network(self.projects[0].id)
        self.service.deallocate_fixed_ip(firstaddress)
        release_ip(mac, firstaddress, hostname, net.bridge_name)

    def test_vpn_ip_and_port_looks_valid(self):
        """Ensure the vpn ip and port are reasonable"""
        self.assert_(self.projects[0].vpn_ip)
        self.assert_(self.projects[0].vpn_port >= FLAGS.vpn_start_port)
        self.assert_(self.projects[0].vpn_port <= FLAGS.vpn_end_port)

    def test_too_many_vpns(self):
        """Ensure error is raised if we run out of vpn ports"""
        vpns = []
        for i in xrange(vpn.NetworkData.num_ports_for_ip(FLAGS.vpn_ip)):
            vpns.append(vpn.NetworkData.create("vpnuser%s" % i))
        self.assertRaises(vpn.NoMorePorts, vpn.NetworkData.create, "boom")
        for network_datum in vpns:
            network_datum.destroy()

    def test_ips_are_reused(self):
        """Makes sure that ip addresses that are deallocated get reused"""
        result = self.service.allocate_fixed_ip(
                     self.projects[0].id)
        mac = result['mac_address']
        address = result['private_dns_name']

        hostname = "reuse-host"
        net = service.get_project_network(self.projects[0].id)

        issue_ip(mac, address, hostname, net.bridge_name)
        self.service.deallocate_fixed_ip(address)
        release_ip(mac, address, hostname, net.bridge_name)

        result = self.service.allocate_fixed_ip(
                self.user, self.projects[0].id)
        secondmac = result['mac_address']
        secondaddress = result['private_dns_name']
        self.assertEqual(address, secondaddress)
        issue_ip(secondmac, secondaddress, hostname, net.bridge_name)
        self.service.deallocate_fixed_ip(secondaddress)
        release_ip(secondmac, secondaddress, hostname, net.bridge_name)

    def test_available_ips(self):
        """Make sure the number of available ips for the network is correct

        The number of available IP addresses depends on the test
        environment's setup.

        Network size is set in test fixture's setUp method.

        There are ips reserved at the bottom and top of the range.
        services (network, gateway, CloudPipe, broadcast)
        """
        net = service.get_project_network(self.projects[0].id)
        num_preallocated_ips = len(net.assigned)
        net_size = flags.FLAGS.network_size
        num_available_ips = net_size - (net.num_bottom_reserved_ips +
                                        num_preallocated_ips +
                                        net.num_top_reserved_ips)
        self.assertEqual(num_available_ips, len(list(net.available)))

    def test_too_many_addresses(self):
        """Test for a NoMoreAddresses exception when all fixed ips are used.
        """
        net = service.get_project_network(self.projects[0].id)

        hostname = "toomany-hosts"
        macs = {}
        addresses = {}
        # Number of availaible ips is len of the available list
        num_available_ips = len(list(net.available))
        for i in range(num_available_ips):
            result = self.service.allocate_fixed_ip(
                                                    self.projects[0].id)
            macs[i] = result['mac_address']
            addresses[i] = result['private_dns_name']
            issue_ip(macs[i], addresses[i], hostname, net.bridge_name)

        self.assertEqual(len(list(net.available)), 0)
        self.assertRaises(NoMoreAddresses,
                          self.service.allocate_fixed_ip,
                          self.projects[0].id,
                          0)

        for i in range(len(addresses)):
            self.service.deallocate_fixed_ip(addresses[i])
            release_ip(macs[i], addresses[i], hostname, net.bridge_name)
        self.assertEqual(len(list(net.available)), num_available_ips)


def is_in_project(address, project_id):
    """Returns true if address is in specified project"""
    return models.FixedIp.find_by_ip_str(address) == service.get_project_network(project_id)


def binpath(script):
    """Returns the absolute path to a script in bin"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


def issue_ip(mac, private_ip, hostname, interface):
    """Run add command on dhcpbridge"""
    cmd = "%s add %s %s %s" % (binpath('nova-dhcpbridge'),
                               mac, private_ip, hostname)
    env = {'DNSMASQ_INTERFACE': interface,
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("ISSUE_IP: %s, %s ", out, err)


def release_ip(mac, private_ip, hostname, interface):
    """Run del command on dhcpbridge"""
    cmd = "%s del %s %s %s" % (binpath('nova-dhcpbridge'),
                               mac, private_ip, hostname)
    env = {'DNSMASQ_INTERFACE': interface,
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("RELEASE_IP: %s, %s ", out, err)
