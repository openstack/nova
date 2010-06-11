# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import logging
import unittest

from nova import vendor
import IPy

from nova import flags
from nova import test
from nova.compute import network
from nova.auth import users
from nova import utils


class NetworkTestCase(test.TrialTestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_storage=True,
                   fake_network=True,
                   network_size=32,
                   redis_db=8)
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = users.UserManager.instance()
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
        self.assertEqual(True, address in self._get_project_addresses("project0"))
        rv = network.deallocate_ip(address)
        self.assertEqual(False, address in self._get_project_addresses("project0"))

    def test_range_allocation(self):
        address = network.allocate_ip(
                "netuser", "project0", utils.generate_mac())
        secondaddress = network.allocate_ip(
                "netuser", "project1", utils.generate_mac())
        self.assertEqual(True,
                         address in self._get_project_addresses("project0"))
        self.assertEqual(True,
                         secondaddress in self._get_project_addresses("project1"))
        self.assertEqual(False, address in self._get_project_addresses("project1"))
        rv = network.deallocate_ip(address)
        self.assertEqual(False, address in self._get_project_addresses("project0"))
        rv = network.deallocate_ip(secondaddress)
        self.assertEqual(False,
                         secondaddress in self._get_project_addresses("project1"))

    def test_subnet_edge(self):
        secondaddress = network.allocate_ip("netuser", "project0",
                                utils.generate_mac())
        for project in range(1,5):
            project_id = "project%s" % (project)
            address = network.allocate_ip(
                    "netuser", project_id, utils.generate_mac())
            address2 = network.allocate_ip(
                    "netuser", project_id, utils.generate_mac())
            address3 = network.allocate_ip(
                    "netuser", project_id, utils.generate_mac())
            self.assertEqual(False,
                             address in self._get_project_addresses("project0"))
            self.assertEqual(False,
                             address2 in self._get_project_addresses("project0"))
            self.assertEqual(False,
                             address3 in self._get_project_addresses("project0"))
            rv = network.deallocate_ip(address)
            rv = network.deallocate_ip(address2)
            rv = network.deallocate_ip(address3)
        rv = network.deallocate_ip(secondaddress)

    def test_too_many_projects(self):
        for i in range(0, 30):
            name = 'toomany-project%s' % i
            self.manager.create_project(name, 'netuser', name)
            address = network.allocate_ip(
                    "netuser", name, utils.generate_mac())
            rv = network.deallocate_ip(address)
            self.manager.delete_project(name)

    def _get_project_addresses(self, project_id):
        project_addresses = []
        for addr in network.get_project_network(project_id).list_addresses():
            project_addresses.append(addr)
        return project_addresses
