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

import mock

from nova import context
from nova import db
from nova import objects
from nova.objects import fields
from nova import test


class ComputeNodeTestCase(test.TestCase):
    def setUp(self):
        super(ComputeNodeTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.cn = objects.ComputeNode(context=self.context,
                                      memory_mb=512, local_gb=1000, vcpus=8,
                                      vcpus_used=0, local_gb_used=0,
                                      memory_mb_used=0, free_ram_mb=0,
                                      free_disk_gb=0, hypervisor_type='danvm',
                                      hypervisor_version=1, cpu_info='barf',
                                      cpu_allocation_ratio=1.0,
                                      ram_allocation_ratio=1.0,
                                      disk_allocation_ratio=1.0)

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    def test_create_creates_inventories(self, mock_minver):
        mock_minver.return_value = 10
        self.cn.create()
        self.assertEqual(512, self.cn.memory_mb)
        self.assertEqual(1000, self.cn.local_gb)
        self.assertEqual(8, self.cn.vcpus)
        db_cn = db.compute_node_get(self.context, self.cn.id)
        self.assertEqual(0, db_cn['memory_mb'])
        self.assertEqual(0, db_cn['local_gb'])
        self.assertEqual(0, db_cn['vcpus'])
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(3, len(inventories))
        inv = {i.resource_class: i.total for i in inventories}
        expected = {
            fields.ResourceClass.DISK_GB: 1000,
            fields.ResourceClass.MEMORY_MB: 512,
            fields.ResourceClass.VCPU: 8,
        }
        self.assertEqual(expected, inv)

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    def test_save_updates_inventories(self, mock_minver):
        mock_minver.return_value = 10
        self.cn.create()
        self.cn.memory_mb = 2048
        self.cn.local_gb = 2000
        self.cn.save()
        self.assertEqual(2048, self.cn.memory_mb)
        self.assertEqual(2000, self.cn.local_gb)
        self.assertEqual(8, self.cn.vcpus)
        db_cn = db.compute_node_get(self.context, self.cn.id)
        self.assertEqual(0, db_cn['memory_mb'])
        self.assertEqual(0, db_cn['local_gb'])
        self.assertEqual(0, db_cn['vcpus'])
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(3, len(inventories))
        inv = {i.resource_class: i.total for i in inventories}
        expected = {
            fields.ResourceClass.DISK_GB: 2000,
            fields.ResourceClass.MEMORY_MB: 2048,
            fields.ResourceClass.VCPU: 8,
        }
        self.assertEqual(expected, inv)

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    def test_save_creates_inventories(self, mock_minver):
        mock_minver.return_value = 7
        self.cn.create()
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(0, len(inventories))
        mock_minver.return_value = 10
        self.cn.memory_mb = 2048
        self.cn.local_gb = 2000
        self.cn.save()
        self.assertEqual(2048, self.cn.memory_mb)
        self.assertEqual(2000, self.cn.local_gb)
        self.assertEqual(8, self.cn.vcpus)
        db_cn = db.compute_node_get(self.context, self.cn.id)
        self.assertEqual(0, db_cn['memory_mb'])
        self.assertEqual(0, db_cn['local_gb'])
        self.assertEqual(0, db_cn['vcpus'])
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(3, len(inventories))
        inv = {i.resource_class: i.total for i in inventories}
        expected = {
            fields.ResourceClass.DISK_GB: 2000,
            fields.ResourceClass.MEMORY_MB: 2048,
            fields.ResourceClass.VCPU: 8,
        }
        self.assertEqual(expected, inv)

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    def test_create_honors_version(self, mock_minver):
        mock_minver.return_value = 7
        self.cn.create()
        self.assertEqual(512, self.cn.memory_mb)
        self.assertEqual(1000, self.cn.local_gb)
        self.assertEqual(8, self.cn.vcpus)
        db_cn = db.compute_node_get(self.context, self.cn.id)
        self.assertEqual(512, db_cn['memory_mb'])
        self.assertEqual(1000, db_cn['local_gb'])
        self.assertEqual(8, db_cn['vcpus'])
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(0, len(inventories))

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    def test_save_honors_version(self, mock_minver):
        mock_minver.return_value = 7
        self.cn.create()
        self.cn.memory_mb = 2048
        self.cn.local_gb = 2000
        self.cn.save()
        self.assertEqual(2048, self.cn.memory_mb)
        self.assertEqual(2000, self.cn.local_gb)
        self.assertEqual(8, self.cn.vcpus)
        db_cn = db.compute_node_get(self.context, self.cn.id)
        self.assertEqual(2048, db_cn['memory_mb'])
        self.assertEqual(2000, db_cn['local_gb'])
        self.assertEqual(8, db_cn['vcpus'])
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        self.assertEqual(0, len(inventories))
