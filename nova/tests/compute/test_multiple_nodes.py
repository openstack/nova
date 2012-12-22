# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NTT DOCOMO, INC.
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
"""Tests for compute service with multiple compute nodes"""

from nova import context
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova import test
from nova.virt import fake


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.config')
CONF.import_opt('compute_driver', 'nova.virt.driver')


class BaseTestCase(test.TestCase):
    def tearDown(self):
        fake.restore_nodes()
        super(BaseTestCase, self).tearDown()


class FakeDriverSingleNodeTestCase(BaseTestCase):
    def setUp(self):
        super(FakeDriverSingleNodeTestCase, self).setUp()
        self.driver = fake.FakeDriver(virtapi=None)
        fake.set_nodes(['xyz'])

    def test_get_host_stats(self):
        stats = self.driver.get_host_stats()
        self.assertTrue(isinstance(stats, dict))
        self.assertEqual(stats['hypervisor_hostname'], 'xyz')

    def test_get_available_resource(self):
        res = self.driver.get_available_resource('xyz')
        self.assertEqual(res['hypervisor_hostname'], 'xyz')


class FakeDriverMultiNodeTestCase(BaseTestCase):
    def setUp(self):
        super(FakeDriverMultiNodeTestCase, self).setUp()
        self.driver = fake.FakeDriver(virtapi=None)
        fake.set_nodes(['aaa', 'bbb'])

    def test_get_host_stats(self):
        stats = self.driver.get_host_stats()
        self.assertTrue(isinstance(stats, list))
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats[0]['hypervisor_hostname'], 'aaa')
        self.assertEqual(stats[1]['hypervisor_hostname'], 'bbb')

    def test_get_available_resource(self):
        res_a = self.driver.get_available_resource('aaa')
        self.assertEqual(res_a['hypervisor_hostname'], 'aaa')

        res_b = self.driver.get_available_resource('bbb')
        self.assertEqual(res_b['hypervisor_hostname'], 'bbb')

        self.assertRaises(exception.NovaException,
                          self.driver.get_available_resource, 'xxx')


class MultiNodeComputeTestCase(BaseTestCase):
    def setUp(self):
        super(MultiNodeComputeTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver')
        self.compute = importutils.import_object(CONF.compute_manager)

    def test_update_available_resource_add_remove_node(self):
        ctx = context.get_admin_context()
        fake.set_nodes(['A', 'B', 'C'])
        self.compute.update_available_resource(ctx)
        self.assertEqual(sorted(self.compute._resource_tracker_dict.keys()),
                         ['A', 'B', 'C'])

        fake.set_nodes(['A', 'B'])
        self.compute.update_available_resource(ctx)
        self.assertEqual(sorted(self.compute._resource_tracker_dict.keys()),
                         ['A', 'B'])

        fake.set_nodes(['A', 'B', 'C'])
        self.compute.update_available_resource(ctx)
        self.assertEqual(sorted(self.compute._resource_tracker_dict.keys()),
                         ['A', 'B', 'C'])
