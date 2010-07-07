# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

import os
import logging
import unittest
import time

from nova import vendor
import IPy

from nova import flags
from nova import test
from nova import exception
from nova.compute.exception import NoMoreAddresses
from nova.compute import network
from nova.auth import users
from nova import utils


class NetworkTestCase(test.TrialTestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_storage=True,
                   fake_network=True,
                   network_size=32)
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = users.UserManager.instance()
        self.dnsmasq = FakeDNSMasq()
        try:
            self.manager.create_user('netuser', 'netuser', 'netuser')
        except: pass
        for i in range(0, 6):
            name = 'project%s' % i
            if not self.manager.get_project(name):
                self.manager.create_project(name, 'netuser', name)
        self.network = network.PublicNetworkController()

    def tearDown(self):
        super(NetworkTestCase, self).tearDown()
        for i in range(0, 6):
            name = 'project%s' % i
            self.manager.delete_project(name)
        self.manager.delete_user('netuser')

    def test_public_network_allocation(self):
        pubnet = IPy.IP(flags.FLAGS.public_range)
        address = self.network.allocate_ip("netuser", "project0", "public")
        self.assertTrue(IPy.IP(address) in pubnet)
        self.assertTrue(IPy.IP(address) in self.network.network)

    def test_allocate_deallocate_ip(self):
        address = network.allocate_ip(
                "netuser", "project0", utils.generate_mac())
        logging.debug("Was allocated %s" % (address))
        net = network.get_project_network("project0", "default")
        self.assertEqual(True, is_in_project(address, "project0"))
        mac = utils.generate_mac()
        hostname = "test-host"
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        rv = network.deallocate_ip(address)
        
        # Doesn't go away until it's dhcp released
        self.assertEqual(True, is_in_project(address, "project0"))
        
        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, "project0"))

    def test_range_allocation(self):
        mac = utils.generate_mac()
        secondmac = utils.generate_mac()
        hostname = "test-host"
        address = network.allocate_ip(
                    "netuser", "project0", mac)
        secondaddress = network.allocate_ip(
                "netuser", "project1", secondmac)
        net = network.get_project_network("project0", "default")
        secondnet = network.get_project_network("project1", "default")
        
        self.assertEqual(True, is_in_project(address, "project0"))
        self.assertEqual(True, is_in_project(secondaddress, "project1"))
        self.assertEqual(False, is_in_project(address, "project1"))
        
        # Addresses are allocated before they're issued
        self.dnsmasq.issue_ip(mac, address, hostname, net.bridge_name)
        self.dnsmasq.issue_ip(secondmac, secondaddress, 
                                hostname, secondnet.bridge_name)
        
        rv = network.deallocate_ip(address)
        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
        self.assertEqual(False, is_in_project(address, "project0"))
        
        # First address release shouldn't affect the second
        self.assertEqual(True, is_in_project(secondaddress, "project1"))
        
        rv = network.deallocate_ip(secondaddress)
        self.dnsmasq.release_ip(secondmac, secondaddress, 
                                hostname, secondnet.bridge_name)
        self.assertEqual(False, is_in_project(secondaddress, "project1"))

    def test_subnet_edge(self):
        secondaddress = network.allocate_ip("netuser", "project0",
                                utils.generate_mac())
        hostname = "toomany-hosts"
        for project in range(1,5):
            project_id = "project%s" % (project)
            mac = utils.generate_mac()
            mac2 = utils.generate_mac()
            mac3 = utils.generate_mac()
            address = network.allocate_ip(
                    "netuser", project_id, mac)
            address2 = network.allocate_ip(
                    "netuser", project_id, mac2)
            address3 = network.allocate_ip(
                    "netuser", project_id, mac3)
            self.assertEqual(False, is_in_project(address, "project0"))
            self.assertEqual(False, is_in_project(address2, "project0"))
            self.assertEqual(False, is_in_project(address3, "project0"))
            rv = network.deallocate_ip(address)
            rv = network.deallocate_ip(address2)
            rv = network.deallocate_ip(address3)
            net = network.get_project_network(project_id, "default")
            self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac2, address2, hostname, net.bridge_name)
            self.dnsmasq.release_ip(mac3, address3, hostname, net.bridge_name)
        net = network.get_project_network("project0", "default")
        rv = network.deallocate_ip(secondaddress)
        self.dnsmasq.release_ip(mac, address, hostname, net.bridge_name)

    def test_release_before_deallocate(self):
        pass
        
    def test_deallocate_before_issued(self):
        pass
    
    def test_too_many_addresses(self):  
        """
        Network size is 32, there are 5 addresses reserved for VPN.
        So we should get 24 usable addresses
        """  
        net = network.get_project_network("project0", "default")
        hostname = "toomany-hosts"
        macs = {}
        addresses = {}
        for i in range(0, 23):
            macs[i] = utils.generate_mac()
            addresses[i] = network.allocate_ip("netuser", "project0", macs[i])
            self.dnsmasq.issue_ip(macs[i], addresses[i], hostname, net.bridge_name)
        
        self.assertRaises(NoMoreAddresses, network.allocate_ip, "netuser", "project0", utils.generate_mac())
        
        for i in range(0, 23):    
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
        cmd = "%s add %s %s %s" % (binpath('dhcpleasor.py'), mac, ip, hostname)
        env = {'DNSMASQ_INTERFACE': interface, 'TESTING' : '1'}
        (out, err) = utils.execute(cmd, addl_env=env)
        logging.debug("ISSUE_IP: %s, %s " % (out, err))
    
    def release_ip(self, mac, ip, hostname, interface):
        cmd = "%s del %s %s %s" % (binpath('dhcpleasor.py'), mac, ip, hostname)
        env = {'DNSMASQ_INTERFACE': interface, 'TESTING' : '1'}
        (out, err) = utils.execute(cmd, addl_env=env)
        logging.debug("RELEASE_IP: %s, %s " % (out, err))
        