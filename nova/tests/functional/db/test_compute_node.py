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

from nova import context
from nova import objects
from nova.objects import fields
from nova import test
from nova.tests import uuidsentinel


class ComputeNodeTestCase(test.TestCase):
    def setUp(self):
        super(ComputeNodeTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.cn = objects.ComputeNode(context=self.context,
                                      uuid=uuidsentinel.compute_node,
                                      memory_mb=512, local_gb=1000, vcpus=8,
                                      vcpus_used=0, local_gb_used=0,
                                      memory_mb_used=0, free_ram_mb=0,
                                      free_disk_gb=0, hypervisor_type='danvm',
                                      hypervisor_version=1, cpu_info='barf',
                                      cpu_allocation_ratio=1.0,
                                      ram_allocation_ratio=1.0,
                                      disk_allocation_ratio=1.0)

    def test_create_inventory(self):
        self.cn.create_inventory()
        objs = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        for obj in objs:
            if obj.resource_class == fields.ResourceClass.VCPU:
                self.assertEqual(8, obj.total)
            elif obj.resource_class == fields.ResourceClass.MEMORY_MB:
                self.assertEqual(512, obj.total)
            elif obj.resource_class == fields.ResourceClass.DISK_GB:
                self.assertEqual(1000, obj.total)

    def test_update_inventory(self):
        self.cn.create_inventory()
        self.cn.memory_mb = 1024
        self.cn.local_gb = 2000
        self.cn.vcpus = 16
        self.cn.update_inventory()
        objs = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, self.cn.uuid)
        for obj in objs:
            if obj.resource_class == fields.ResourceClass.VCPU:
                self.assertEqual(16, obj.total)
            elif obj.resource_class == fields.ResourceClass.MEMORY_MB:
                self.assertEqual(1024, obj.total)
            elif obj.resource_class == fields.ResourceClass.DISK_GB:
                self.assertEqual(2000, obj.total)
