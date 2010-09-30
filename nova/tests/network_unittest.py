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
from nova import test
from nova import utils
from nova.auth import manager
from nova.api.ec2 import context

FLAGS = flags.FLAGS


class NetworkTestCase(test.TrialTestCase):
    """Test cases for network code"""
    def setUp(self):  # pylint: disable-msg=C0103
        super(NetworkTestCase, self).setUp()
        # NOTE(vish): if you change these flags, make sure to change the
        #             flags in the corresponding section in nova-dhcpbridge
        self.flags(connection_type='fake',
                   fake_network=True,
                   auth_driver='nova.auth.ldapdriver.FakeLdapDriver',
                   network_size=16,
                   num_networks=5)
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('netuser', 'netuser', 'netuser')
        self.projects = []
        self.network = utils.import_object(FLAGS.network_manager)
        self.context = context.APIRequestContext(project=None, user=self.user)
        for i in range(5):
            name = 'project%s' % i
            self.projects.append(self.manager.create_project(name,
                                                             'netuser',
                                                             name))
            # create the necessary network data for the project
            user_context = context.APIRequestContext(project=self.projects[i],
                                                     user=self.user)
            self.network.set_network_host(user_context, self.projects[i].id)
        instance_ref = db.instance_create(None,
                                         {'mac_address': utils.generate_mac()})
        self.instance_id = instance_ref['id']
        instance_ref = db.instance_create(None,
                                         {'mac_address': utils.generate_mac()})
        self.instance2_id = instance_ref['id']

    def tearDown(self):  # pylint: disable-msg=C0103
        super(NetworkTestCase, self).tearDown()
        # TODO(termie): this should really be instantiating clean datastores
        #               in between runs, one failure kills all the tests
        db.instance_destroy(None, self.instance_id)
        db.instance_destroy(None, self.instance2_id)
        for project in self.projects:
            self.manager.delete_project(project)
        self.manager.delete_user(self.user)

    def _create_address(self, project_num, instance_id=None):
        """Create an address in given project num"""
        if instance_id is None:
            instance_id = self.instance_id
        self.context.project = self.projects[project_num]
        return self.network.allocate_fixed_ip(self.context, instance_id)

    def test_public_network_association(self):
        """Makes sure that we can allocaate a public ip"""
        # TODO(vish): better way of adding floating ips
        self.context.project = self.projects[0]
        pubnet = IPy.IP(flags.FLAGS.public_range)
        address = str(pubnet[0])
        try:
            db.floating_ip_get_by_address(None, address)
        except exception.NotFound:
            db.floating_ip_create(None, {'address': address,
                                         'host': FLAGS.host})
        float_addr = self.network.allocate_floating_ip(self.context,
                                                       self.projects[0].id)
        fix_addr = self._create_address(0)
        self.assertEqual(float_addr, str(pubnet[0]))
        self.network.associate_floating_ip(self.context, float_addr, fix_addr)
        address = db.instance_get_floating_address(None, self.instance_id)
        self.assertEqual(address, float_addr)
        self.network.disassociate_floating_ip(self.context, float_addr)
        address = db.instance_get_floating_address(None, self.instance_id)
        self.assertEqual(address, None)
        self.network.deallocate_floating_ip(self.context, float_addr)
        self.network.deallocate_fixed_ip(self.context, fix_addr)

    def test_allocate_deallocate_fixed_ip(self):
        """Makes sure that we can allocate and deallocate a fixed ip"""
        address = self._create_address(0)
        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))
        lease_ip(address)
        self.network.deallocate_fixed_ip(self.context, address)

        # Doesn't go away until it's dhcp released
        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))

        release_ip(address)
        self.assertFalse(is_allocated_in_project(address, self.projects[0].id))

    def test_side_effects(self):
        """Ensures allocating and releasing has no side effects"""
        address = self._create_address(0)
        address2 = self._create_address(1, self.instance2_id)

        self.assertTrue(is_allocated_in_project(address, self.projects[0].id))
        self.assertTrue(is_allocated_in_project(address2, self.projects[1].id))
        self.assertFalse(is_allocated_in_project(address, self.projects[1].id))

        # Addresses are allocated before they're issued
        lease_ip(address)
        lease_ip(address2)

        self.network.deallocate_fixed_ip(self.context, address)
        release_ip(address)
        self.assertFalse(is_allocated_in_project(address, self.projects[0].id))

        # First address release shouldn't affect the second
        self.assertTrue(is_allocated_in_project(address2, self.projects[1].id))

        self.network.deallocate_fixed_ip(self.context, address2)
        release_ip(address2)
        self.assertFalse(is_allocated_in_project(address2,
                                                 self.projects[1].id))

    def test_subnet_edge(self):
        """Makes sure that private ips don't overlap"""
        first = self._create_address(0)
        lease_ip(first)
        instance_ids = []
        for i in range(1, 5):
            mac = utils.generate_mac()
            instance_ref = db.instance_create(None,
                                              {'mac_address': mac})
            instance_ids.append(instance_ref['id'])
            address = self._create_address(i, instance_ref['id'])
            mac = utils.generate_mac()
            instance_ref = db.instance_create(None,
                                              {'mac_address': mac})
            instance_ids.append(instance_ref['id'])
            address2 = self._create_address(i, instance_ref['id'])
            mac = utils.generate_mac()
            instance_ref = db.instance_create(None,
                                              {'mac_address': mac})
            instance_ids.append(instance_ref['id'])
            address3 = self._create_address(i, instance_ref['id'])
            lease_ip(address)
            lease_ip(address2)
            lease_ip(address3)
            self.assertFalse(is_allocated_in_project(address,
                                                     self.projects[0].id))
            self.assertFalse(is_allocated_in_project(address2,
                                                     self.projects[0].id))
            self.assertFalse(is_allocated_in_project(address3,
                                                     self.projects[0].id))
            self.network.deallocate_fixed_ip(self.context, address)
            self.network.deallocate_fixed_ip(self.context, address2)
            self.network.deallocate_fixed_ip(self.context, address3)
            release_ip(address)
            release_ip(address2)
            release_ip(address3)
        for instance_id in instance_ids:
            db.instance_destroy(None, instance_id)
        release_ip(first)
        self.network.deallocate_fixed_ip(self.context, first)

    def test_vpn_ip_and_port_looks_valid(self):
        """Ensure the vpn ip and port are reasonable"""
        self.assert_(self.projects[0].vpn_ip)
        self.assert_(self.projects[0].vpn_port >= FLAGS.vpn_start)
        self.assert_(self.projects[0].vpn_port <= FLAGS.vpn_start +
                                                  FLAGS.num_networks)

    def test_too_many_networks(self):
        """Ensure error is raised if we run out of networks"""
        projects = []
        networks_left = FLAGS.num_networks - db.network_count(None)
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
        address = self._create_address(0)
        lease_ip(address)
        self.network.deallocate_fixed_ip(self.context, address)
        release_ip(address)

        address2 = self._create_address(0)
        self.assertEqual(address, address2)
        self.network.deallocate_fixed_ip(self.context, address2)

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
        total_ips = (db.network_count_available_ips(None, network['id']) +
                     db.network_count_reserved_ips(None, network['id']) +
                     db.network_count_allocated_ips(None, network['id']))
        self.assertEqual(total_ips, net_size)

    def test_too_many_addresses(self):
        """Test for a NoMoreAddresses exception when all fixed ips are used.
        """
        network = db.project_get_network(None, self.projects[0].id)
        num_available_ips = db.network_count_available_ips(None,
                                                           network['id'])
        addresses = []
        instance_ids = []
        for i in range(num_available_ips):
            mac = utils.generate_mac()
            instance_ref = db.instance_create(None,
                                              {'mac_address': mac})
            instance_ids.append(instance_ref['id'])
            address = self._create_address(0, instance_ref['id'])
            addresses.append(address)
            lease_ip(address)

        self.assertEqual(db.network_count_available_ips(None,
                                                        network['id']), 0)
        self.assertRaises(db.NoMoreAddresses,
                          self.network.allocate_fixed_ip,
                          self.context,
                          'foo')

        for i in range(num_available_ips):
            self.network.deallocate_fixed_ip(self.context, addresses[i])
            release_ip(addresses[i])
            db.instance_destroy(None, instance_ids[i])
        self.assertEqual(db.network_count_available_ips(None,
                                                        network['id']),
                         num_available_ips)


def is_allocated_in_project(address, project_id):
    """Returns true if address is in specified project"""
    project_net = db.project_get_network(None, project_id)
    network = db.fixed_ip_get_network(None, address)
    instance = db.fixed_ip_get_instance(None, address)
    # instance exists until release
    return instance is not None and network['id'] == project_net['id']


def binpath(script):
    """Returns the absolute path to a script in bin"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


def lease_ip(private_ip):
    """Run add command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(None, private_ip)
    instance_ref = db.fixed_ip_get_instance(None, private_ip)
    cmd = "%s add %s %s fake" % (binpath('nova-dhcpbridge'),
                                 instance_ref['mac_address'],
                                 private_ip)
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("ISSUE_IP: %s, %s ", out, err)


def release_ip(private_ip):
    """Run del command on dhcpbridge"""
    network_ref = db.fixed_ip_get_network(None, private_ip)
    instance_ref = db.fixed_ip_get_instance(None, private_ip)
    cmd = "%s del %s %s fake" % (binpath('nova-dhcpbridge'),
                                 instance_ref['mac_address'],
                                 private_ip)
    env = {'DNSMASQ_INTERFACE': network_ref['bridge'],
           'TESTING': '1',
           'FLAGFILE': FLAGS.dhcpbridge_flagfile}
    (out, err) = utils.execute(cmd, addl_env=env)
    logging.debug("RELEASE_IP: %s, %s ", out, err)
