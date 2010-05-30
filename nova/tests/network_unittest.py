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


class NetworkTestCase(test.TrialTestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        logging.getLogger().setLevel(logging.DEBUG)
        self.manager = users.UserManager.instance()
        try:
            self.manager.create_user('netuser', 'netuser', 'netuser')
        except: pass
        for i in range(0, 6):
            name = 'project%s' % i
            if not self.manager.get_project(name):
                self.manager.create_project(name, 'netuser', name)
        self.network = network.NetworkController(netsize=16)

    def tearDown(self):
        super(NetworkTestCase, self).tearDown()
        for i in range(0, 6):
            name = 'project%s' % i
            self.manager.delete_project(name)
        self.manager.delete_user('netuser')

    def test_network_serialization(self):
        net1 = network.Network(vlan=100, network="192.168.100.0/24", conn=None)
        address = net1.allocate_ip("netuser", "project0", "01:24:55:36:f2:a0")
        net_json = str(net1)
        net2 = network.Network.from_json(net_json)
        self.assertEqual(net_json, str(net2))
        self.assertTrue(IPy.IP(address) in net2.network)

    def test_allocate_deallocate_address(self):
        (address, net_name) = self.network.allocate_address("netuser",
                "project0", "01:24:55:36:f2:a0")
        logging.debug("Was allocated %s" % (address))
        self.assertEqual(True, address in self._get_project_addresses("project0"))
        rv = self.network.deallocate_address(address)
        self.assertEqual(False, address in self._get_project_addresses("project0"))

    def test_range_allocation(self):
        (address, net_name) = self.network.allocate_address("netuser",
                "project0", "01:24:55:36:f2:a0")
        (secondaddress, net_name) = self.network.allocate_address("netuser",
                "project1", "01:24:55:36:f2:a0")
        self.assertEqual(True, address in self._get_project_addresses("project0"))
        self.assertEqual(True,
                         secondaddress in self._get_project_addresses("project1"))
        self.assertEqual(False, address in self._get_project_addresses("project1"))
        rv = self.network.deallocate_address(address)
        self.assertEqual(False, address in self._get_project_addresses("project0"))
        rv = self.network.deallocate_address(secondaddress)
        self.assertEqual(False,
                         secondaddress in self._get_project_addresses("project1"))

    def test_subnet_edge(self):
        (secondaddress, net_name) = self.network.allocate_address("netuser", "project0")
        for project in range(1,5):
            project_id = "project%s" % (project)
            (address, net_name) = self.network.allocate_address("netuser",
                    project_id, "01:24:55:36:f2:a0")
            (address2, net_name) = self.network.allocate_address("netuser",
                    project_id, "01:24:55:36:f2:a0")
            (address3, net_name) = self.network.allocate_address("netuser",
                    project_id, "01:24:55:36:f2:a0")
            self.assertEqual(False,
                             address in self._get_project_addresses("project0"))
            self.assertEqual(False,
                             address2 in self._get_project_addresses("project0"))
            self.assertEqual(False,
                             address3 in self._get_project_addresses("project0"))
            rv = self.network.deallocate_address(address)
            rv = self.network.deallocate_address(address2)
            rv = self.network.deallocate_address(address3)
        rv = self.network.deallocate_address(secondaddress)

    def test_too_many_projects(self):
        for i in range(0, 30):
            name = 'toomany-project%s' % i
            self.manager.create_project(name, 'netuser', name)
            (address, net_name) = self.network.allocate_address("netuser",
                    name, "01:24:55:36:f2:a0")
            self.manager.delete_project(name)

    def _get_project_addresses(self, project_id):
        rv = self.network.describe_addresses()
        project_addresses = []
        for item in rv:
            if item['project_id'] == project_id:
                project_addresses.append(item['address'])
        return project_addresses
