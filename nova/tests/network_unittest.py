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

from nova import db
from nova import exception
from nova import flags
from nova import models
from nova import test
from nova import utils
from nova.auth import manager
from nova.network import service

FLAGS = flags.FLAGS


class NetworkTestCase(test.TrialTestCase):
    """Test cases for network code"""
    def setUp(self):  # pylint: disable-msg=C0103
        super(NetworkTestCase, self).setUp()
        # NOTE(vish): if you change these flags, make sure to change the
        #             flags in the corresponding section in nova-dhcpbridge
        self.flags(connection_type='fake',
                   fake_storage=True,
                   fake_network=True,
                   auth_driver='nova.auth.ldapdriver.FakeLdapDriver',
                   network_size=16,
                   num_networks=5)
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('netuser', 'netuser', 'netuser')
        self.projects = []
        self.service = service.VlanNetworkService()
        for i in range(5):
            name = 'project%s' % i
            self.projects.append(self.manager.create_project(name,
                                                             'netuser',
                                                             name))
            # create the necessary network data for the project
            self.service.set_network_host(self.projects[i].id)
        instance_id = db.instance_create(None,
                                         {'mac_address': utils.generate_mac()})
        self.instance_id = instance_id
        instance_id = db.instance_create(None,
                                         {'mac_address': utils.generate_mac()})
        self.instance2_id = instance_id

    def tearDown(self):  # pylint: disable-msg=C0103
        super(NetworkTestCase, self).tearDown()
        # TODO(termie): this should really be instantiating clean datastores
        #               in between runs, one failure kills all the tests
        db.instance_destroy(None, self.instance_id)
        db.instance_destroy(None, self.instance2_id)
        for project in self.projects:
            self.manager.delete_project(project)
        self.manager.delete_user(self.user)

    def test_public_network_association(self):
        """Makes sure that we can allocaate a public ip"""
        # TODO(vish): better way of adding floating ips
        pubnet = IPy.IP(flags.FLAGS.public_range)
        ip_str = str(pubnet[0])
        try:
            floating_ip = models.FloatingIp.find_by_ip_str(ip_str)
        except exception.NotFound:
            floating_ip = models.FloatingIp()
            floating_ip.ip_str = ip_str
            floating_ip.node_name = FLAGS.node_name
            floating_ip.save()
        eaddress = self.service.allocate_floating_ip(self.projects[0].id)
        faddress = self.service.allocate_fixed_ip(self.projects[0].id,
                                                 self.instance_id)
        self.assertEqual(eaddress, str(pubnet[0]))
        self.service.associate_floating_ip(eaddress, faddress)
        # FIXME datamodel abstraction
        self.assertEqual(floating_ip.fixed_ip.ip_str, faddress)
        self.service.disassociate_floating_ip(eaddress)
        self.assertEqual(floating_ip.fixed_ip, None)
        self.service.deallocate_floating_ip(eaddress)
        self.service.deallocate_fixed_ip(faddress)

    def test_allocate_deallocate_fixed_ip(self):
        """Makes sure that we can allocate and deallocate a fixed ip"""
        address = self.service.allocate_fixed_ip(self.projects[0].id,
                                                 self.instance_id)
        net = db.project_get_network(None, self.projects[0].id)
        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))
        issue_ip(address, net.bridge)
        self.service.deallocate_fixed_ip(address)

        # Doesn't go away until it's dhcp released
        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))

        release_ip(address, net.bridge)
        self.assertFalse(is_allocated_in_project(address, self.projects[0].id))

    def test_side_effects(self):
        """Ensures allocating and releasing has no side effects"""
        address = self.service.allocate_fixed_ip(self.projects[0].id,
                                                 self.instance_id)
        address2 = self.service.allocate_fixed_ip(self.projects[1].id,
                                                  self.instance2_id)

        net = db.project_get_network(None, self.projects[0].id)
        net2 = db.project_get_network(None, self.projects[1].id)

        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))
        self.assertTrue(is_allocated_in_project(address2, self.projects[1].id))
        self.assertFalse(is_allocated_in_project(address, self.projects[1].id))

        # Addresses are allocated before they're issued
        issue_ip(address, net.bridge)
        issue_ip(address2, net2.bridge)

        self.service.deallocate_fixed_ip(address)
        release_ip(address, net.bridge)
        self.assertFalse(is_allocated_in_project(address, self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertTrue(is_allocated_in_project(address2, self.projects[1].id))

        self.service.deallocate_fixed_ip(address2)
        release_ip(address2, net2.bridge)
        self.assertFalse(is_allocated_in_project(address2, self.projects[1].id))

    def test_subnet_edge(self):
        """Makes sure that private ips don't overlap"""
        first = self.service.allocate_fixed_ip(self.projects[0].id,
                                               self.instance_id)
        for i in range(1, 5):
            project_id = self.projects[i].id
            address = self.service.allocate_fixed_ip(project_id, self.instance_id)
            address2 = self.service.allocate_fixed_ip(project_id, self.instance_id)
            address3 = self.service.allocate_fixed_ip(project_id, self.instance_id)
            net = db.project_get_network(None, project_id)
            issue_ip(address, net.bridge)
            issue_ip(address2, net.bridge)
            issue_ip(address3, net.bridge)
            self.assertFalse(is_allocated_in_project(address,
                                                     self.projects[0].id))
            self.assertFalse(is_allocated_in_project(address2,
                                                     self.projects[0].id))
            self.assertFalse(is_allocated_in_project(address3,
                                                     self.projects[0].id))
            self.service.deallocate_fixed_ip(address)
            self.service.deallocate_fixed_ip(address2)
            self.service.deallocate_fixed_ip(address3)
            release_ip(address, net.bridge)
            release_ip(address2, net.bridge)
            release_ip(address3, net.bridge)
        net = db.project_get_network(None, self.projects[0].id)
        self.service.deallocate_fixed_ip(first)

    def test_vpn_ip_and_port_looks_valid(self):
        """Ensure the vpn ip and port are reasonable"""
        self.assert_(self.projects[0].vpn_ip)
        self.assert_(self.projects[0].vpn_port >= FLAGS.vpn_start)
        self.assert_(self.projects[0].vpn_port <= FLAGS.vpn_start +
                                                  FLAGS.num_networks)

    def test_too_many_networks(self):
        """Ensure error is raised if we run out of networks"""
        projects = []
        # TODO(vish): use data layer for count
        networks_left = FLAGS.num_networks - models.Network.count()
        for i in range(networks_left):
            project = self.manager.create_project('many%s' % i, self.user)
            projects.append(project)
        self.assertRaises(db.NoMoreNetworks,
                          self.manager.create_project,
                          'boom',
                          self.user)
        for project in projects:
            self.manager.delete_project(project)


    def test_ips_are_reused(self):
        """Makes sure that ip addresses that are deallocated get reused"""
        address = self.service.allocate_fixed_ip(self.projects[0].id,
                                                 self.instance_id)
        net = db.project_get_network(None, self.projects[0].id)
        issue_ip(address, net.bridge)
        self.service.deallocate_fixed_ip(address)
        release_ip(address, net.bridge)

        address2 = self.service.allocate_fixed_ip(self.projects[0].id,
                                                  self.instance_id)
        self.assertEqual(address, address2)
        self.service.deallocate_fixed_ip(address2)

    def test_available_ips(self):
        """Make sure the number of available ips for the network is correct

        The number of available IP addresses depends on the test
        environment's setup.

        Network size is set in test fixture's setUp method.

        There are ips reserved at the bottom and top of the range.
        services (network, gateway, CloudPipe, broadcast)
        """
        network = db.project_get_network(None, self.projects[0].id)
        net_size = flags.FLAGS.network_size
        total_ips = (available_ips(network) +
                     reserved_ips(network) +
                     allocated_ips(network))
        self.assertEqual(total_ips, net_size)

    def test_too_many_addresses(self):
        """Test for a NoMoreAddresses exception when all fixed ips are used.
        """
        network = db.project_get_network(None, self.projects[0].id)

        # Number of availaible ips is len of the available list

        num_available_ips = available_ips(network)
        addresses = []
        for i in range(num_available_ips):
            project_id = self.projects[0].id
            addresses.append(self.service.allocate_fixed_ip(project_id,
                                                            self.instance_id))
            issue_ip(addresses[i],network.bridge)

        self.assertEqual(available_ips(network), 0)
        self.assertRaises(db.NoMoreAddresses,
                          self.service.allocate_fixed_ip,
                          self.projects[0].id,
                          self.instance_id)

        for i in range(len(addresses)):
            self.service.deallocate_fixed_ip(addresses[i])
            release_ip(addresses[i],network.bridge)
        self.assertEqual(available_ips(network), num_available_ips)


# FIXME move these to abstraction layer
def available_ips(network):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network.id)
    query = query.filter_by(allocated=False).filter_by(reserved=False)
    return query.count()

def allocated_ips(network):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network.id)
    query = query.filter_by(allocated=True)
    return query.count()

def reserved_ips(network):
    session = models.NovaBase.get_session()
    query = session.query(models.FixedIp).filter_by(network_id=network.id)
    query = query.filter_by(reserved=True)
    return query.count()

def is_allocated_in_project(address, project_id):
    """Returns true if address is in specified project"""
    fixed_ip = db.fixed_ip_get_by_address(None, address)
    project_net = db.project_get_network(None, project_id)
    # instance exists until release
    logging.debug('fixed_ip.instance: %s', fixed_ip.instance)
    logging.debug('project_net: %s', project_net)
    return fixed_ip.instance is not None and fixed_ip.network == project_net


def binpath(script):
    """Returns the absolute path to a script in bin"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


def issue_ip(private_ip, interface):
    """Run add command on dhcpbridge"""
    cmd = "%s add fake %s fake" % (binpath('nova-dhcpbridge'), private_ip)
    env = {'DNSMASQ_INTERFACE': interface,
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("ISSUE_IP: %s, %s ", out, err)


def release_ip(private_ip, interface):
    """Run del command on dhcpbridge"""
    cmd = "%s del fake %s fake" % (binpath('nova-dhcpbridge'), private_ip)
    env = {'DNSMASQ_INTERFACE': interface,
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("RELEASE_IP: %s, %s ", out, err)
