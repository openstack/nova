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
"""Tests for compute service with multiple compute nodes."""

from oslo_config import cfg
from oslo_utils import importutils

from nova import context
from nova import db
from nova import objects
from nova import test
from nova.virt import fake


CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
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

    def test_get_available_resource(self):
        res = self.driver.get_available_resource('xyz')
        self.assertEqual(res['hypervisor_hostname'], 'xyz')


class FakeDriverMultiNodeTestCase(BaseTestCase):
    def setUp(self):
        super(FakeDriverMultiNodeTestCase, self).setUp()
        self.driver = fake.FakeDriver(virtapi=None)
        fake.set_nodes(['aaa', 'bbb'])

    def test_get_available_resource(self):
        res_a = self.driver.get_available_resource('aaa')
        self.assertEqual(res_a['hypervisor_hostname'], 'aaa')

        res_b = self.driver.get_available_resource('bbb')
        self.assertEqual(res_b['hypervisor_hostname'], 'bbb')

        res_x = self.driver.get_available_resource('xxx')
        self.assertEqual(res_x, {})


class MultiNodeComputeTestCase(BaseTestCase):
    def setUp(self):
        super(MultiNodeComputeTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver')
        self.compute = importutils.import_object(CONF.compute_manager)
        self.flags(use_local=True, group='conductor')
        self.conductor = self.start_service('conductor',
                                            manager=CONF.conductor.manager)

        def fake_get_compute_nodes_in_db(context, use_slave=False):
            fake_compute_nodes = [{'local_gb': 259,
                                   'vcpus_used': 0,
                                   'deleted': 0,
                                   'hypervisor_type': 'powervm',
                                   'created_at': '2013-04-01T00:27:06.000000',
                                   'local_gb_used': 0,
                                   'updated_at': '2013-04-03T00:35:41.000000',
                                   'hypervisor_hostname': 'fake_phyp1',
                                   'memory_mb_used': 512,
                                   'memory_mb': 131072,
                                   'current_workload': 0,
                                   'vcpus': 16,
                                   'cpu_info': 'ppc64,powervm,3940',
                                   'running_vms': 0,
                                   'free_disk_gb': 259,
                                   'service_id': 7,
                                   'hypervisor_version': 7,
                                   'disk_available_least': 265856,
                                   'deleted_at': None,
                                   'free_ram_mb': 130560,
                                   'metrics': '',
                                   'numa_topology': '',
                                   'stats': '',
                                   'id': 2,
                                   'host': 'fake_phyp1',
                                   'host_ip': '127.0.0.1'}]
            return [objects.ComputeNode._from_db_object(
                        context, objects.ComputeNode(), cn)
                    for cn in fake_compute_nodes]

        def fake_compute_node_delete(context, compute_node_id):
            self.assertEqual(2, compute_node_id)

        self.stubs.Set(self.compute, '_get_compute_nodes_in_db',
                fake_get_compute_nodes_in_db)
        self.stubs.Set(db, 'compute_node_delete',
                fake_compute_node_delete)

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

    def test_compute_manager_removes_deleted_node(self):
        ctx = context.get_admin_context()
        fake.set_nodes(['A', 'B'])

        fake_compute_nodes = [
            objects.ComputeNode(
                context=ctx, hypervisor_hostname='A', id=2),
            objects.ComputeNode(
                context=ctx, hypervisor_hostname='B', id=3),
            ]

        def fake_get_compute_nodes_in_db(context, use_slave=False):
            return fake_compute_nodes

        def fake_compute_node_delete(context, compute_node_id):
            for cn in fake_compute_nodes:
                if compute_node_id == cn.id:
                    fake_compute_nodes.remove(cn)
                    return

        self.stubs.Set(self.compute, '_get_compute_nodes_in_db',
                fake_get_compute_nodes_in_db)
        self.stubs.Set(db, 'compute_node_delete',
                fake_compute_node_delete)

        self.compute.update_available_resource(ctx)

        # Verify nothing is deleted if driver and db compute nodes match
        self.assertEqual(len(fake_compute_nodes), 2)
        self.assertEqual(sorted(self.compute._resource_tracker_dict.keys()),
                         ['A', 'B'])

        fake.set_nodes(['A'])
        self.compute.update_available_resource(ctx)

        # Verify B gets deleted since now only A is reported by driver
        self.assertEqual(len(fake_compute_nodes), 1)
        self.assertEqual(fake_compute_nodes[0]['hypervisor_hostname'], 'A')
        self.assertEqual(sorted(self.compute._resource_tracker_dict.keys()),
                        ['A'])
