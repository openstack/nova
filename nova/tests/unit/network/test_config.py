# Copyright 2016 HPE, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import nova.network
import nova.network.security_group.neutron_driver
import nova.network.security_group.openstack_driver as sgapi
import nova.test


class NetworkAPIConfigTest(nova.test.NoDBTestCase):
    """Test the transition from legacy to use_neutron config options."""

    def setUp(self):
        super(NetworkAPIConfigTest, self).setUp()
        self.flags(use_neutron=False)

    def test_default(self):
        netapi = nova.network.API()
        self.assertIsInstance(netapi, nova.network.api.API)

    def test_use_neutron(self):
        self.flags(use_neutron=True)
        netapi = nova.network.API()
        self.assertIsInstance(netapi, nova.network.neutronv2.api.API)

    def test_dont_use_neutron(self):
        self.flags(use_neutron=False)
        netapi = nova.network.API()
        self.assertIsInstance(netapi, nova.network.api.API)


class SecurityGroupAPIConfigTest(nova.test.NoDBTestCase):

    def test_use_neutron(self):
        self.flags(use_neutron=True)
        driver = sgapi.get_openstack_security_group_driver()
        self.assertIsInstance(
            driver,
            nova.network.security_group.neutron_driver.SecurityGroupAPI)

    def test_sg_nova(self):
        self.flags(use_neutron=False)
        driver = sgapi.get_openstack_security_group_driver()
        self.assertIsInstance(
            driver,
            nova.compute.api.SecurityGroupAPI)
