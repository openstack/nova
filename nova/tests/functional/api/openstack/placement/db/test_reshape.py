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

from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.tests.functional.api.openstack.placement.db import test_base as tb
from nova.tests import uuidsentinel as uuids


def alloc_for_rc(alloc_list, rc):
    for alloc in alloc_list:
        if alloc.resource_class == rc:
            return alloc


class ReshapeTestCase(tb.PlacementDbBaseTestCase):
    """Test 'replace the world' reshape transaction."""

    def test_reshape(self):
        """We set up the following scenario:

        BEFORE: single compute node setup

          A single compute node with:
            - VCPU, MEMORY_MB, DISK_GB inventory
            - Two instances consuming CPU, RAM and DISK from that compute node

        AFTER: hierarchical + shared storage setup

          A compute node parent provider with:
            - MEMORY_MB
          Two NUMA node child providers containing:
            - VCPU
          Shared storage provider with:
            - DISK_GB
          Both instances have their resources split among the providers and
          shared storage accordingly
        """
        # First create our consumers
        i1_uuid = uuids.instance1
        i1_consumer = consumer_obj.Consumer(
            self.ctx, uuid=i1_uuid, user=self.user_obj,
            project=self.project_obj)
        i1_consumer.create()

        i2_uuid = uuids.instance2
        i2_consumer = consumer_obj.Consumer(
            self.ctx, uuid=i2_uuid, user=self.user_obj,
            project=self.project_obj)
        i2_consumer.create()

        cn1 = self._create_provider('cn1')
        tb.add_inventory(cn1, 'VCPU', 16)
        tb.add_inventory(cn1, 'MEMORY_MB', 32768)
        tb.add_inventory(cn1, 'DISK_GB', 1000)

        # Allocate both instances against the single compute node
        for consumer in (i1_consumer, i2_consumer):
            allocs = [
                rp_obj.Allocation(
                    self.ctx, resource_provider=cn1,
                    resource_class='VCPU', consumer=consumer, used=2),
                rp_obj.Allocation(
                    self.ctx, resource_provider=cn1,
                    resource_class='MEMORY_MB', consumer=consumer, used=1024),
                rp_obj.Allocation(
                    self.ctx, resource_provider=cn1,
                    resource_class='DISK_GB', consumer=consumer, used=100),
            ]
            alloc_list = rp_obj.AllocationList(self.ctx, objects=allocs)
            alloc_list.replace_all()

        # Verify we have the allocations we expect for the BEFORE scenario
        before_allocs_i1 = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, i1_uuid)
        self.assertEqual(3, len(before_allocs_i1))
        self.assertEqual(cn1.uuid, before_allocs_i1[0].resource_provider.uuid)
        before_allocs_i2 = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, i2_uuid)
        self.assertEqual(3, len(before_allocs_i2))
        self.assertEqual(cn1.uuid, before_allocs_i2[2].resource_provider.uuid)

        # Before we issue the actual reshape() call, we need to first create
        # the child providers and sharing storage provider. These are actions
        # that the virt driver or external agent is responsible for performing
        # *before* attempting any reshape activity.
        cn1_numa0 = self._create_provider('cn1_numa0', parent=cn1.uuid)
        cn1_numa1 = self._create_provider('cn1_numa1', parent=cn1.uuid)
        ss = self._create_provider('ss')

        # OK, now emulate the call to POST /reshaper that will be triggered by
        # a virt driver wanting to replace the world and change its modeling
        # from a single provider to a nested provider tree along with a sharing
        # storage provider.
        after_inventories = {
            # cn1 keeps the RAM only
            cn1.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1,
                    resource_class='MEMORY_MB', total=32768, reserved=0,
                    max_unit=32768, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            # each NUMA node gets half of the CPUs
            cn1_numa0.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1_numa0,
                    resource_class='VCPU', total=8, reserved=0,
                    max_unit=8, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            cn1_numa1.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1_numa1,
                    resource_class='VCPU', total=8, reserved=0,
                    max_unit=8, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            # The sharing provider gets a bunch of disk
            ss.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=ss,
                    resource_class='DISK_GB', total=100000, reserved=0,
                    max_unit=1000, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
        }
        # We do a fetch from the DB for each instance to get its latest
        # generation. This would be done by the resource tracker or scheduler
        # report client before issuing the call to reshape() because the
        # consumers representing the two instances above will have had their
        # generations incremented in the original call to PUT
        # /allocations/{consumer_uuid}
        i1_consumer = consumer_obj.Consumer.get_by_uuid(self.ctx, i1_uuid)
        i2_consumer = consumer_obj.Consumer.get_by_uuid(self.ctx, i2_uuid)
        after_allocs = rp_obj.AllocationList(self.ctx, objects=[
            # instance1 gets VCPU from NUMA0, MEMORY_MB from cn1 and DISK_GB
            # from the sharing storage provider
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1_numa0, resource_class='VCPU',
                consumer=i1_consumer, used=2),
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1, resource_class='MEMORY_MB',
                consumer=i1_consumer, used=1024),
            rp_obj.Allocation(
                self.ctx, resource_provider=ss, resource_class='DISK_GB',
                consumer=i1_consumer, used=100),
            # instance2 gets VCPU from NUMA1, MEMORY_MB from cn1 and DISK_GB
            # from the sharing storage provider
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1_numa1, resource_class='VCPU',
                consumer=i2_consumer, used=2),
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1, resource_class='MEMORY_MB',
                consumer=i2_consumer, used=1024),
            rp_obj.Allocation(
                self.ctx, resource_provider=ss, resource_class='DISK_GB',
                consumer=i2_consumer, used=100),
        ])
        rp_obj.reshape(self.ctx, after_inventories, after_allocs)

        # Verify that the inventories have been moved to the appropriate
        # providers in the AFTER scenario

        # The root compute node should only have MEMORY_MB, nothing else
        cn1_inv = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, cn1)
        self.assertEqual(1, len(cn1_inv))
        self.assertEqual('MEMORY_MB', cn1_inv[0].resource_class)
        self.assertEqual(32768, cn1_inv[0].total)
        # Each NUMA node should only have half the original VCPU, nothing else
        numa0_inv = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, cn1_numa0)
        self.assertEqual(1, len(numa0_inv))
        self.assertEqual('VCPU', numa0_inv[0].resource_class)
        self.assertEqual(8, numa0_inv[0].total)
        numa1_inv = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, cn1_numa1)
        self.assertEqual(1, len(numa1_inv))
        self.assertEqual('VCPU', numa1_inv[0].resource_class)
        self.assertEqual(8, numa1_inv[0].total)
        # The sharing storage provider should only have DISK_GB, nothing else
        ss_inv = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, ss)
        self.assertEqual(1, len(ss_inv))
        self.assertEqual('DISK_GB', ss_inv[0].resource_class)
        self.assertEqual(100000, ss_inv[0].total)

        # Verify we have the allocations we expect for the AFTER scenario
        after_allocs_i1 = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, i1_uuid)
        self.assertEqual(3, len(after_allocs_i1))
        # Our VCPU allocation should be in the NUMA0 node
        vcpu_alloc = alloc_for_rc(after_allocs_i1, 'VCPU')
        self.assertIsNotNone(vcpu_alloc)
        self.assertEqual(cn1_numa0.uuid, vcpu_alloc.resource_provider.uuid)
        # Our DISK_GB allocation should be in the sharing provider
        disk_alloc = alloc_for_rc(after_allocs_i1, 'DISK_GB')
        self.assertIsNotNone(disk_alloc)
        self.assertEqual(ss.uuid, disk_alloc.resource_provider.uuid)
        # And our MEMORY_MB should remain on the root compute node
        ram_alloc = alloc_for_rc(after_allocs_i1, 'MEMORY_MB')
        self.assertIsNotNone(ram_alloc)
        self.assertEqual(cn1.uuid, ram_alloc.resource_provider.uuid)

        after_allocs_i2 = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, i2_uuid)
        self.assertEqual(3, len(after_allocs_i2))
        # Our VCPU allocation should be in the NUMA1 node
        vcpu_alloc = alloc_for_rc(after_allocs_i2, 'VCPU')
        self.assertIsNotNone(vcpu_alloc)
        self.assertEqual(cn1_numa1.uuid, vcpu_alloc.resource_provider.uuid)
        # Our DISK_GB allocation should be in the sharing provider
        disk_alloc = alloc_for_rc(after_allocs_i2, 'DISK_GB')
        self.assertIsNotNone(disk_alloc)
        self.assertEqual(ss.uuid, disk_alloc.resource_provider.uuid)
        # And our MEMORY_MB should remain on the root compute node
        ram_alloc = alloc_for_rc(after_allocs_i2, 'MEMORY_MB')
        self.assertIsNotNone(ram_alloc)
        self.assertEqual(cn1.uuid, ram_alloc.resource_provider.uuid)

    def test_reshape_concurrent_inventory_update(self):
        """Valid failure scenario for reshape(). We test a situation where the
        virt driver has constructed it's "after inventories and allocations"
        and sent those to the POST /reshape endpoint. The reshape POST handler
        does a quick check of the resource provider generations sent in the
        payload and they all check out.

        However, right before the call to resource_provider.reshape(), another
        thread legitimately changes the inventory of one of the providers
        involved in the reshape transaction. We should get a
        ConcurrentUpdateDetected in this case.
        """
        # First create our consumers
        i1_uuid = uuids.instance1
        i1_consumer = consumer_obj.Consumer(
            self.ctx, uuid=i1_uuid, user=self.user_obj,
            project=self.project_obj)
        i1_consumer.create()

        # then all our original providers
        cn1 = self._create_provider('cn1')
        tb.add_inventory(cn1, 'VCPU', 16)
        tb.add_inventory(cn1, 'MEMORY_MB', 32768)
        tb.add_inventory(cn1, 'DISK_GB', 1000)

        # Allocate an instance on our compute node
        allocs = [
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1,
                resource_class='VCPU', consumer=i1_consumer, used=2),
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1,
                resource_class='MEMORY_MB', consumer=i1_consumer, used=1024),
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1,
                resource_class='DISK_GB', consumer=i1_consumer, used=100),
        ]
        alloc_list = rp_obj.AllocationList(self.ctx, objects=allocs)
        alloc_list.replace_all()

        # Before we issue the actual reshape() call, we need to first create
        # the child providers and sharing storage provider. These are actions
        # that the virt driver or external agent is responsible for performing
        # *before* attempting any reshape activity.
        cn1_numa0 = self._create_provider('cn1_numa0', parent=cn1.uuid)
        cn1_numa1 = self._create_provider('cn1_numa1', parent=cn1.uuid)
        ss = self._create_provider('ss')

        # OK, now emulate the call to POST /reshaper that will be triggered by
        # a virt driver wanting to replace the world and change its modeling
        # from a single provider to a nested provider tree along with a sharing
        # storage provider.
        after_inventories = {
            # cn1 keeps the RAM only
            cn1.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1,
                    resource_class='MEMORY_MB', total=32768, reserved=0,
                    max_unit=32768, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            # each NUMA node gets half of the CPUs
            cn1_numa0.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1_numa0,
                    resource_class='VCPU', total=8, reserved=0,
                    max_unit=8, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            cn1_numa1.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=cn1_numa1,
                    resource_class='VCPU', total=8, reserved=0,
                    max_unit=8, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
            # The sharing provider gets a bunch of disk
            ss.uuid: rp_obj.InventoryList(self.ctx, objects=[
                rp_obj.Inventory(
                    self.ctx, resource_provider=ss,
                    resource_class='DISK_GB', total=100000, reserved=0,
                    max_unit=1000, min_unit=1, step_size=1,
                    allocation_ratio=1.0),
            ]),
        }
        # We do a fetch from the DB for each instance to get its latest
        # generation. This would be done by the resource tracker or scheduler
        # report client before issuing the call to reshape() because the
        # consumers representing the two instances above will have had their
        # generations incremented in the original call to PUT
        # /allocations/{consumer_uuid}
        i1_consumer = consumer_obj.Consumer.get_by_uuid(self.ctx, i1_uuid)
        after_allocs = rp_obj.AllocationList(self.ctx, objects=[
            # instance1 gets VCPU from NUMA0, MEMORY_MB from cn1 and DISK_GB
            # from the sharing storage provider
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1_numa0, resource_class='VCPU',
                consumer=i1_consumer, used=2),
            rp_obj.Allocation(
                self.ctx, resource_provider=cn1, resource_class='MEMORY_MB',
                consumer=i1_consumer, used=1024),
            rp_obj.Allocation(
                self.ctx, resource_provider=ss, resource_class='DISK_GB',
                consumer=i1_consumer, used=100),
        ])

        # OK, now before we call reshape(), here we emulate another thread
        # changing the inventory for the sharing storage provider in between
        # the time in the REST handler when the sharing storage provider's
        # generation was validated and the actual call to reshape()
        ss_threadB = rp_obj.ResourceProvider.get_by_uuid(self.ctx, ss.uuid)
        # Reduce the amount of storage to 2000, from 100000.
        new_ss_inv = rp_obj.InventoryList(self.ctx, objects=[
            rp_obj.Inventory(
                self.ctx, resource_provider=ss_threadB,
                resource_class='DISK_GB', total=2000, reserved=0,
                    max_unit=1000, min_unit=1, step_size=1,
                    allocation_ratio=1.0)])
        ss_threadB.set_inventory(new_ss_inv)
        # Double check our storage provider's generation is now greater than
        # the original storage provider record being sent to reshape()
        self.assertGreater(ss_threadB.generation, ss.generation)

        # And we should legitimately get a failure now to reshape() due to
        # another thread updating one of the involved provider's generations
        self.assertRaises(
            exception.ConcurrentUpdateDetected,
            rp_obj.reshape, self.ctx, after_inventories, after_allocs)
