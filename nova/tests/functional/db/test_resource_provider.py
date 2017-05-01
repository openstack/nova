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
from oslo_db import exception as db_exc

import nova
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.objects import resource_provider as rp_obj
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel

DISK_INVENTORY = dict(
    total=200,
    reserved=10,
    min_unit=2,
    max_unit=5,
    step_size=1,
    allocation_ratio=1.0,
    resource_class=fields.ResourceClass.DISK_GB
)

DISK_ALLOCATION = dict(
    consumer_id=uuidsentinel.disk_consumer,
    used=2,
    resource_class=fields.ResourceClass.DISK_GB
)


class ResourceProviderBaseCase(test.NoDBTestCase):

    USES_DB_SELF = True

    def setUp(self):
        super(ResourceProviderBaseCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.api_db = self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _make_allocation(self, rp_uuid=None, inv_dict=None):
        rp_uuid = rp_uuid or uuidsentinel.allocation_resource_provider
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=rp_uuid,
            name=rp_uuid)
        rp.create()
        inv_dict = inv_dict or DISK_INVENTORY
        disk_inv = objects.Inventory(context=self.context,
                resource_provider=rp, **inv_dict)
        disk_inv.create()
        inv_list = objects.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)
        alloc = objects.Allocation(self.context, resource_provider=rp,
                **DISK_ALLOCATION)
        alloc_list = objects.AllocationList(self.context, objects=[alloc])
        alloc_list.create_all()
        return rp, alloc


class ResourceProviderTestCase(ResourceProviderBaseCase):
    """Test resource-provider objects' lifecycles."""

    def test_create_resource_provider_requires_uuid(self):
        resource_provider = objects.ResourceProvider(
            context = self.context)
        self.assertRaises(exception.ObjectActionError,
                          resource_provider.create)

    def test_create_resource_provider(self):
        created_resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
        self.assertIsInstance(created_resource_provider.id, int)

        retrieved_resource_provider = objects.ResourceProvider.get_by_uuid(
            self.context,
            uuidsentinel.fake_resource_provider
        )
        self.assertEqual(retrieved_resource_provider.id,
                         created_resource_provider.id)
        self.assertEqual(retrieved_resource_provider.uuid,
                         created_resource_provider.uuid)
        self.assertEqual(retrieved_resource_provider.name,
                         created_resource_provider.name)
        self.assertEqual(0, created_resource_provider.generation)
        self.assertEqual(0, retrieved_resource_provider.generation)

    def test_save_resource_provider(self):
        created_resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
        created_resource_provider.name = 'new-name'
        created_resource_provider.save()
        retrieved_resource_provider = objects.ResourceProvider.get_by_uuid(
            self.context,
            uuidsentinel.fake_resource_provider
        )
        self.assertEqual('new-name', retrieved_resource_provider.name)

    def test_destroy_resource_provider(self):
        created_resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
        created_resource_provider.destroy()
        self.assertRaises(exception.NotFound,
                          objects.ResourceProvider.get_by_uuid,
                          self.context,
                          uuidsentinel.fake_resource_provider)
        self.assertRaises(exception.NotFound,
                          created_resource_provider.destroy)

    def test_destroy_allocated_resource_provider_fails(self):
        rp, allocation = self._make_allocation()
        self.assertRaises(exception.ResourceProviderInUse,
                          rp.destroy)

    def test_destroy_resource_provider_destroy_inventory(self):
        resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        resource_provider.create()
        disk_inventory = objects.Inventory(
            context=self.context,
            resource_provider=resource_provider,
            **DISK_INVENTORY
        )
        disk_inventory.create()
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid)
        self.assertEqual(1, len(inventories))
        resource_provider.destroy()
        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid)
        self.assertEqual(0, len(inventories))

    def test_create_inventory_with_uncreated_provider(self):
        resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.inventory_resource_provider
        )
        disk_inventory = objects.Inventory(
            context=self.context,
            resource_provider=resource_provider,
            **DISK_INVENTORY
        )
        self.assertRaises(exception.ObjectActionError,
                          disk_inventory.create)

    def test_create_and_update_inventory(self):
        resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.inventory_resource_provider,
            name='foo',
        )
        resource_provider.create()
        resource_class = fields.ResourceClass.DISK_GB
        disk_inventory = objects.Inventory(
            context=self.context,
            resource_provider=resource_provider,
            **DISK_INVENTORY
        )
        disk_inventory.create()

        self.assertEqual(resource_class, disk_inventory.resource_class)
        self.assertEqual(resource_provider,
                         disk_inventory.resource_provider)
        self.assertEqual(DISK_INVENTORY['allocation_ratio'],
                         disk_inventory.allocation_ratio)
        self.assertEqual(DISK_INVENTORY['total'],
                         disk_inventory.total)

        disk_inventory.total = 32
        disk_inventory.save()

        inventories = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid)

        self.assertEqual(1, len(inventories))
        self.assertEqual(32, inventories[0].total)

        inventories[0].total = 33
        inventories[0].save()
        reloaded_inventories = (
            objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid))
        self.assertEqual(33, reloaded_inventories[0].total)

    def test_set_inventory_unknown_resource_class(self):
        """Test attempting to set inventory to an unknown resource class raises
        an exception.
        """
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.rp_uuid,
            name='compute-host',
        )
        rp.create()

        inv = objects.Inventory(
            resource_provider=rp,
            resource_class='UNKNOWN',
            total=1024,
            reserved=15,
            min_unit=10,
            max_unit=100,
            step_size=10,
            allocation_ratio=1.0,
        )

        inv_list = objects.InventoryList(objects=[inv])
        self.assertRaises(exception.ResourceClassNotFound,
                          rp.set_inventory, inv_list)

    def test_set_inventory_fail_in_used(self):
        """Test attempting to set inventory which would result in removing an
        inventory record for a resource class that still has allocations
        against it.
        """
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.rp_uuid,
            name='compute-host',
        )
        rp.create()

        inv = objects.Inventory(
            resource_provider=rp,
            resource_class='VCPU',
            total=12,
            reserved=0,
            min_unit=1,
            max_unit=12,
            step_size=1,
            allocation_ratio=1.0,
        )

        inv_list = objects.InventoryList(objects=[inv])
        rp.set_inventory(inv_list)

        alloc = objects.Allocation(
            resource_provider=rp,
            resource_class='VCPU',
            consumer_id=uuidsentinel.consumer,
            used=1,
        )

        alloc_list = objects.AllocationList(
            self.context,
            objects=[alloc]
        )
        alloc_list.create_all()

        inv = objects.Inventory(
            resource_provider=rp,
            resource_class='MEMORY_MB',
            total=1024,
            reserved=0,
            min_unit=256,
            max_unit=1024,
            step_size=256,
            allocation_ratio=1.0,
        )

        inv_list = objects.InventoryList(objects=[inv])
        self.assertRaises(exception.InventoryInUse,
                          rp.set_inventory,
                          inv_list)

    @mock.patch('nova.objects.resource_provider.LOG')
    def test_set_inventory_over_capacity(self, mock_log):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=uuidsentinel.rp_uuid,
                                      name=uuidsentinel.rp_name)
        rp.create()

        disk_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=2048,
                reserved=15,
                min_unit=10,
                max_unit=600,
                step_size=10,
                allocation_ratio=1.0)
        vcpu_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                total=12,
                reserved=0,
                min_unit=1,
                max_unit=12,
                step_size=1,
                allocation_ratio=16.0)

        inv_list = objects.InventoryList(objects=[disk_inv, vcpu_inv])
        rp.set_inventory(inv_list)
        self.assertFalse(mock_log.warning.called)

        # Allocate something reasonable for the above inventory
        alloc = objects.Allocation(
            context=self.context,
            resource_provider=rp,
            consumer_id=uuidsentinel.consumer,
            resource_class='DISK_GB',
            used=500)
        alloc_list = objects.AllocationList(self.context, objects=[alloc])
        alloc_list.create_all()

        # Update our inventory to over-subscribe us after the above allocation
        disk_inv.total = 400
        rp.set_inventory(inv_list)

        # We should succeed, but have logged a warning for going over on disk
        mock_log.warning.assert_called_once_with(
            mock.ANY, {'uuid': rp.uuid, 'resource': 'DISK_GB'})

    def test_provider_modify_inventory(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=uuidsentinel.rp_uuid,
                                      name=uuidsentinel.rp_name)
        rp.create()
        saved_generation = rp.generation

        disk_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=1024,
                reserved=15,
                min_unit=10,
                max_unit=100,
                step_size=10,
                allocation_ratio=1.0)

        vcpu_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                total=12,
                reserved=0,
                min_unit=1,
                max_unit=12,
                step_size=1,
                allocation_ratio=16.0)

        # set to new list
        inv_list = objects.InventoryList(objects=[disk_inv, vcpu_inv])
        rp.set_inventory(inv_list)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        self.assertEqual(2, len(new_inv_list))
        resource_classes = [inv.resource_class for inv in new_inv_list]
        self.assertIn(fields.ResourceClass.VCPU, resource_classes)
        self.assertIn(fields.ResourceClass.DISK_GB, resource_classes)

        # reset list to just disk_inv
        inv_list = objects.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        self.assertEqual(1, len(new_inv_list))
        resource_classes = [inv.resource_class for inv in new_inv_list]
        self.assertNotIn(fields.ResourceClass.VCPU, resource_classes)
        self.assertIn(fields.ResourceClass.DISK_GB, resource_classes)
        self.assertEqual(1024, new_inv_list[0].total)

        # update existing disk inv to new settings
        disk_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=2048,
                reserved=15,
                min_unit=10,
                max_unit=100,
                step_size=10,
                allocation_ratio=1.0)
        rp.update_inventory(disk_inv)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        self.assertEqual(1, len(new_inv_list))
        self.assertEqual(2048, new_inv_list[0].total)

        # fail when inventory bad
        disk_inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=2048,
                reserved=2048)
        disk_inv.obj_set_defaults()
        error = self.assertRaises(exception.InvalidInventoryCapacity,
                                  rp.update_inventory, disk_inv)
        self.assertIn("Invalid inventory for '%s'"
                      % fields.ResourceClass.DISK_GB, str(error))
        self.assertIn("on resource provider '%s'." % rp.uuid, str(error))

        # generation has not bumped
        self.assertEqual(saved_generation, rp.generation)

        # delete inventory
        rp.delete_inventory(fields.ResourceClass.DISK_GB)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        result = new_inv_list.find(fields.ResourceClass.DISK_GB)
        self.assertIsNone(result)
        self.assertRaises(exception.NotFound, rp.delete_inventory,
                          fields.ResourceClass.DISK_GB)

        # check inventory list is empty
        inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        self.assertEqual(0, len(inv_list))

        # add some inventory
        rp.add_inventory(vcpu_inv)
        inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
                self.context, uuidsentinel.rp_uuid)
        self.assertEqual(1, len(inv_list))

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        # add same inventory again
        self.assertRaises(db_exc.DBDuplicateEntry,
                          rp.add_inventory, vcpu_inv)

        # generation has not bumped
        self.assertEqual(saved_generation, rp.generation)

        # fail when generation wrong
        rp.generation = rp.generation - 1
        self.assertRaises(exception.ConcurrentUpdateDetected,
                          rp.set_inventory, inv_list)

    def test_delete_inventory_not_found(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=uuidsentinel.rp_uuid,
                                      name=uuidsentinel.rp_name)
        rp.create()
        error = self.assertRaises(exception.NotFound, rp.delete_inventory,
                                  'DISK_GB')
        self.assertIn('No inventory of class DISK_GB found for delete',
                      str(error))

    def test_delete_inventory_with_allocation(self):
        rp, allocation = self._make_allocation(inv_dict=DISK_INVENTORY)
        error = self.assertRaises(exception.InventoryInUse,
                                  rp.delete_inventory,
                                  'DISK_GB')
        self.assertIn(
            "Inventory for 'DISK_GB' on resource provider '%s' in use"
            % rp.uuid, str(error))

    def test_update_inventory_not_found(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=uuidsentinel.rp_uuid,
                                      name=uuidsentinel.rp_name)
        rp.create()
        disk_inv = objects.Inventory(resource_provider=rp,
                                     resource_class='DISK_GB',
                                     total=2048)
        disk_inv.obj_set_defaults()
        error = self.assertRaises(exception.NotFound, rp.update_inventory,
                                  disk_inv)
        self.assertIn('No inventory of class DISK_GB found',
                      str(error))

    @mock.patch('nova.objects.resource_provider.LOG')
    def test_update_inventory_violates_allocation(self, mock_log):
        # Compute nodes that are reconfigured have to be able to set
        # their inventory to something that violates allocations so
        # we need to make that possible.
        rp, allocation = self._make_allocation()
        # attempt to set inventory to less than currently allocated
        # amounts
        new_total = 1
        disk_inv = objects.Inventory(
            resource_provider=rp,
            resource_class=fields.ResourceClass.DISK_GB, total=new_total)
        disk_inv.obj_set_defaults()
        rp.update_inventory(disk_inv)

        usages = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(allocation.used, usages[0].usage)

        inv_list = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(new_total, inv_list[0].total)
        mock_log.warning.assert_called_once_with(
            mock.ANY, {'uuid': rp.uuid, 'resource': 'DISK_GB'})

    def test_add_invalid_inventory(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=uuidsentinel.rp_uuid,
                                      name=uuidsentinel.rp_name)
        rp.create()
        disk_inv = objects.Inventory(
            resource_provider=rp,
            resource_class=fields.ResourceClass.DISK_GB,
            total=1024, reserved=2048)
        disk_inv.obj_set_defaults()
        error = self.assertRaises(exception.InvalidInventoryCapacity,
                                  rp.add_inventory,
                                  disk_inv)
        self.assertIn("Invalid inventory for '%s'"
                      % fields.ResourceClass.DISK_GB, str(error))
        self.assertIn("on resource provider '%s'."
                      % rp.uuid, str(error))

    def test_add_allocation_increments_generation(self):
        rp = objects.ResourceProvider(context=self.context,
                uuid=uuidsentinel.inventory_resource_provider, name='foo')
        rp.create()
        inv = objects.Inventory(context=self.context, resource_provider=rp,
                **DISK_INVENTORY)
        inv.create()
        expected_gen = rp.generation + 1
        alloc = objects.Allocation(context=self.context, resource_provider=rp,
                **DISK_ALLOCATION)
        alloc_list = objects.AllocationList(self.context, objects=[alloc])
        alloc_list.create_all()
        self.assertEqual(expected_gen, rp.generation)


class ResourceProviderListTestCase(ResourceProviderBaseCase):
    def setUp(self):
        super(ResourceProviderListTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_get_all_by_filters(self):
        for rp_i in ['1', '2']:
            uuid = getattr(uuidsentinel, 'rp_uuid_' + rp_i)
            name = 'rp_name_' + rp_i
            rp = objects.ResourceProvider(self.context, name=name, uuid=uuid)
            rp.create()

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context)
        self.assertEqual(2, len(resource_providers))
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'uuid': getattr(uuidsentinel, 'rp_uuid_2')})
        self.assertEqual(1, len(resource_providers))
        self.assertEqual('rp_name_2', resource_providers[0].name)

    def test_get_all_by_filters_with_resources(self):
        for rp_i in ['1', '2']:
            uuid = getattr(uuidsentinel, 'rp_uuid_' + rp_i)
            name = 'rp_name_' + rp_i
            rp = objects.ResourceProvider(self.context, name=name, uuid=uuid)
            rp.create()
            inv = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                min_unit=1,
                max_unit=2,
                total=2,
                allocation_ratio=1.0)
            inv.obj_set_defaults()

            inv2 = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=1024, reserved=2,
                min_unit=1,
                max_unit=1024,
                allocation_ratio=1.0)
            inv2.obj_set_defaults()

            # Write that specific inventory for testing min/max units and steps
            inv3 = objects.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024, reserved=2,
                min_unit=2,
                max_unit=4,
                step_size=2,
                allocation_ratio=1.0)
            inv3.obj_set_defaults()

            inv_list = objects.InventoryList(objects=[inv, inv2, inv3])
            rp.set_inventory(inv_list)

            # Create the VCPU allocation only for the first RP
            if rp_i != '1':
                continue
            allocation_1 = objects.Allocation(
                resource_provider=rp,
                consumer_id=uuidsentinel.consumer,
                resource_class=fields.ResourceClass.VCPU,
                used=1)
            allocation_list = objects.AllocationList(
                self.context, objects=[allocation_1])
            allocation_list.create_all()

        # Both RPs should accept that request given the only current allocation
        # for the first RP is leaving one VCPU
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.VCPU: 1}})
        self.assertEqual(2, len(resource_providers))
        # Now, when asking for 2 VCPUs, only the second RP should accept that
        # given the current allocation for the first RP
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.VCPU: 2}})
        self.assertEqual(1, len(resource_providers))
        # Adding a second resource request should be okay for the 2nd RP
        # given it has enough disk but we also need to make sure that the
        # first RP is not acceptable because of the VCPU request
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.VCPU: 2,
                                         fields.ResourceClass.DISK_GB: 1022}})
        self.assertEqual(1, len(resource_providers))
        # Now, we are asking for both disk and VCPU resources that all the RPs
        # can't accept (as the 2nd RP is having a reserved size)
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.VCPU: 2,
                                         fields.ResourceClass.DISK_GB: 1024}})
        self.assertEqual(0, len(resource_providers))

        # We also want to verify that asking for a specific RP can also be
        # checking the resource usage.
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'name': u'rp_name_1',
                           'resources': {fields.ResourceClass.VCPU: 1}})
        self.assertEqual(1, len(resource_providers))

        # Let's verify that the min and max units are checked too
        # Case 1: amount is in between min and max and modulo step_size
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.MEMORY_MB: 2}})
        self.assertEqual(2, len(resource_providers))
        # Case 2: amount is less than min_unit
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.MEMORY_MB: 1}})
        self.assertEqual(0, len(resource_providers))
        # Case 3: amount is more than min_unit
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.MEMORY_MB: 5}})
        self.assertEqual(0, len(resource_providers))
        # Case 4: amount is not modulo step_size
        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, {'resources': {fields.ResourceClass.MEMORY_MB: 3}})
        self.assertEqual(0, len(resource_providers))

    def test_get_all_by_filters_with_resources_not_existing(self):
        self.assertRaises(
            exception.ResourceClassNotFound,
            objects.ResourceProviderList.get_all_by_filters,
            self.context, {'resources': {'FOOBAR': 3}})

    def test_get_all_by_filters_aggregate(self):
        for rp_i in [1, 2, 3, 4]:
            uuid = getattr(uuidsentinel, 'rp_uuid_' + str(rp_i))
            name = 'rp_name_' + str(rp_i)
            rp = objects.ResourceProvider(self.context, name=name, uuid=uuid)
            rp.create()
            if rp_i % 2:
                aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
                rp.set_aggregates(aggregate_uuids)

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'member_of': [uuidsentinel.agg_a]})

        self.assertEqual(2, len(resource_providers))
        names = [_rp.name for _rp in resource_providers]
        self.assertIn('rp_name_1', names)
        self.assertIn('rp_name_3', names)
        self.assertNotIn('rp_name_2', names)
        self.assertNotIn('rp_name_4', names)

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b]})
        self.assertEqual(2, len(resource_providers))

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b],
                                   'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b],
                                   'name': u'barnabas'})
        self.assertEqual(0, len(resource_providers))

        resource_providers = objects.ResourceProviderList.get_all_by_filters(
            self.context, filters={'member_of':
                                   [uuidsentinel.agg_1, uuidsentinel.agg_2]})
        self.assertEqual(0, len(resource_providers))


class TestResourceProviderAggregates(test.NoDBTestCase):

    USES_DB_SELF = True

    def setUp(self):
        super(TestResourceProviderAggregates, self).setUp()
        self.useFixture(fixtures.Database(database='main'))
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_set_and_get_new_aggregates(self):
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.rp_uuid,
            name=uuidsentinel.rp_name
        )
        rp.create()

        aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp.set_aggregates(aggregate_uuids)

        read_aggregate_uuids = rp.get_aggregates()
        self.assertItemsEqual(aggregate_uuids, read_aggregate_uuids)

        # Since get_aggregates always does a new query this is
        # mostly nonsense but is here for completeness.
        read_rp = objects.ResourceProvider.get_by_uuid(
            self.context, uuidsentinel.rp_uuid)
        re_read_aggregate_uuids = read_rp.get_aggregates()
        self.assertItemsEqual(aggregate_uuids, re_read_aggregate_uuids)

    def test_set_aggregates_is_replace(self):
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.rp_uuid,
            name=uuidsentinel.rp_name
        )
        rp.create()

        start_aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp.set_aggregates(start_aggregate_uuids)
        read_aggregate_uuids = rp.get_aggregates()
        self.assertItemsEqual(start_aggregate_uuids, read_aggregate_uuids)

        rp.set_aggregates([uuidsentinel.agg_a])
        read_aggregate_uuids = rp.get_aggregates()
        self.assertNotIn(uuidsentinel.agg_b, read_aggregate_uuids)
        self.assertIn(uuidsentinel.agg_a, read_aggregate_uuids)

        # Empty list means delete.
        rp.set_aggregates([])
        read_aggregate_uuids = rp.get_aggregates()
        self.assertEqual([], read_aggregate_uuids)

    def test_delete_rp_clears_aggs(self):
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.rp_uuid,
            name=uuidsentinel.rp_name
        )
        rp.create()
        rp_id = rp.id
        start_aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp.set_aggregates(start_aggregate_uuids)
        aggs = objects.ResourceProvider._get_aggregates(self.context, rp_id)
        self.assertEqual(2, len(aggs))
        rp.destroy()
        aggs = objects.ResourceProvider._get_aggregates(self.context, rp_id)
        self.assertEqual(0, len(aggs))


class TestAllocation(ResourceProviderBaseCase):

    def test_create_list_and_delete_allocation(self):
        resource_provider = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.allocation_resource_provider,
            name=uuidsentinel.allocation_resource_name
        )
        resource_provider.create()
        resource_class = fields.ResourceClass.DISK_GB
        inv = objects.Inventory(context=self.context,
                resource_provider=resource_provider, **DISK_INVENTORY)
        inv.create()
        disk_allocation = objects.Allocation(
            context=self.context,
            resource_provider=resource_provider,
            **DISK_ALLOCATION
        )
        alloc_list = objects.AllocationList(self.context,
                objects=[disk_allocation])
        alloc_list.create_all()

        self.assertEqual(resource_class, disk_allocation.resource_class)
        self.assertEqual(resource_provider,
                         disk_allocation.resource_provider)
        self.assertEqual(DISK_ALLOCATION['used'],
                         disk_allocation.used)
        self.assertEqual(DISK_ALLOCATION['consumer_id'],
                         disk_allocation.consumer_id)
        self.assertIsInstance(disk_allocation.id, int)

        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid)

        self.assertEqual(1, len(allocations))

        self.assertEqual(DISK_ALLOCATION['used'],
                        allocations[0].used)

        allocations[0].destroy()

        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, resource_provider.uuid)

        self.assertEqual(0, len(allocations))

    def test_destroy(self):
        rp, allocation = self._make_allocation()
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(1, len(allocations))
        objects.Allocation._destroy(self.context, allocation.id)
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(0, len(allocations))
        self.assertRaises(exception.NotFound, objects.Allocation._destroy,
                          self.context, allocation.id)

    def test_get_allocations_from_db(self):
        rp, allocation = self._make_allocation()
        allocations = objects.AllocationList._get_allocations_from_db(
            self.context, rp.uuid)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp.id, allocations[0].resource_provider_id)
        self.assertEqual(allocation.resource_provider.id,
                         allocations[0].resource_provider_id)

        allocations = objects.AllocationList._get_allocations_from_db(
            self.context, uuidsentinel.bad_rp_uuid)
        self.assertEqual(0, len(allocations))

    def test_get_all_by_resource_provider(self):
        rp, allocation = self._make_allocation()
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp.id, allocations[0].resource_provider.id)
        self.assertEqual(allocation.resource_provider.id,
                         allocations[0].resource_provider.id)

    def test_get_all_multiple_providers(self):
        # This confirms that the join with resource provider is
        # behaving.
        rp1, allocation1 = self._make_allocation(uuidsentinel.rp1)
        rp2, allocation2 = self._make_allocation(uuidsentinel.rp2)
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp1.uuid)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp1.id, allocations[0].resource_provider.id)
        self.assertEqual(allocation1.resource_provider.id,
                         allocations[0].resource_provider.id)

        # add more allocations for the first resource provider
        # of the same class
        alloc3 = objects.Allocation(
            self.context,
            consumer_id=uuidsentinel.consumer1,
            resource_class=fields.ResourceClass.DISK_GB,
            resource_provider=rp1,
            used=2,
        )
        alloc_list = objects.AllocationList(self.context, objects=[alloc3])
        alloc_list.create_all()
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp1.uuid)
        self.assertEqual(2, len(allocations))

        # add more allocations for the first resource provider
        # of a different class
        # First we need to add sufficient inventory
        res_cls = fields.ResourceClass.IPV4_ADDRESS
        inv = objects.Inventory(self.context, resource_provider=rp1,
                resource_class=res_cls, total=256, max_unit=10)
        inv.obj_set_defaults()
        inv.create()
        # Now allocate 4 of them.
        alloc4 = objects.Allocation(
            self.context,
            consumer_id=uuidsentinel.consumer2,
            resource_class=res_cls,
            resource_provider=rp1,
            used=4,
        )
        alloc_list = objects.AllocationList(self.context, objects=[alloc4])
        alloc_list.create_all()
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp1.uuid)
        self.assertEqual(3, len(allocations))
        self.assertEqual(rp1.uuid, allocations[0].resource_provider.uuid)

        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp2.uuid)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp2.uuid, allocations[0].resource_provider.uuid)
        self.assertIn(fields.ResourceClass.DISK_GB,
                      [allocation.resource_class
                       for allocation in allocations])
        self.assertNotIn(fields.ResourceClass.IPV4_ADDRESS,
                      [allocation.resource_class
                       for allocation in allocations])


class TestAllocationListCreateDelete(ResourceProviderBaseCase):

    def test_allocation_checking(self):
        """Test that allocation check logic works with 2 resource classes on
        one provider.

        If this fails, we get a KeyError at create_all()
        """

        max_unit = 10
        consumer_uuid = uuidsentinel.consumer
        consumer_uuid2 = uuidsentinel.consumer2

        # Create one resource provider with 2 classes
        rp1_name = uuidsentinel.rp1_name
        rp1_uuid = uuidsentinel.rp1_uuid
        rp1_class = fields.ResourceClass.DISK_GB
        rp1_used = 6

        rp2_class = fields.ResourceClass.IPV4_ADDRESS
        rp2_used = 2

        rp1 = objects.ResourceProvider(
            self.context, name=rp1_name, uuid=rp1_uuid)
        rp1.create()

        inv = objects.Inventory(resource_provider=rp1,
                                resource_class=rp1_class,
                                total=1024, max_unit=max_unit)
        inv.obj_set_defaults()

        inv2 = objects.Inventory(resource_provider=rp1,
                                 resource_class=rp2_class,
                                 total=255, reserved=2,
                                 max_unit=max_unit)
        inv2.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv, inv2])
        rp1.set_inventory(inv_list)

        # create the allocations for a first consumer
        allocation_1 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid,
                                          resource_class=rp1_class,
                                          used=rp1_used)
        allocation_2 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid,
                                          resource_class=rp2_class,
                                          used=rp2_used)
        allocation_list = objects.AllocationList(
            self.context, objects=[allocation_1, allocation_2])
        allocation_list.create_all()

        # create the allocations for a second consumer, until we have
        # allocations for more than one consumer in the db, then we
        # won't actually be doing real allocation math, which triggers
        # the sql monster.
        allocation_1 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid2,
                                          resource_class=rp1_class,
                                          used=rp1_used)
        allocation_2 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid2,
                                          resource_class=rp2_class,
                                          used=rp2_used)
        allocation_list = objects.AllocationList(
            self.context, objects=[allocation_1, allocation_2])
        # If we are joining wrong, this will be a KeyError
        allocation_list.create_all()

    def test_allocation_list_create(self):
        max_unit = 10
        consumer_uuid = uuidsentinel.consumer

        # Create two resource providers
        rp1_name = uuidsentinel.rp1_name
        rp1_uuid = uuidsentinel.rp1_uuid
        rp1_class = fields.ResourceClass.DISK_GB
        rp1_used = 6

        rp2_name = uuidsentinel.rp2_name
        rp2_uuid = uuidsentinel.rp2_uuid
        rp2_class = fields.ResourceClass.IPV4_ADDRESS
        rp2_used = 2

        rp1 = objects.ResourceProvider(
            self.context, name=rp1_name, uuid=rp1_uuid)
        rp1.create()
        rp2 = objects.ResourceProvider(
            self.context, name=rp2_name, uuid=rp2_uuid)
        rp2.create()

        # Two allocations, one for each resource provider.
        allocation_1 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid,
                                          resource_class=rp1_class,
                                          used=rp1_used)
        allocation_2 = objects.Allocation(resource_provider=rp2,
                                          consumer_id=consumer_uuid,
                                          resource_class=rp2_class,
                                          used=rp2_used)
        allocation_list = objects.AllocationList(
            self.context, objects=[allocation_1, allocation_2])

        # There's no inventory, we have a failure.
        error = self.assertRaises(exception.InvalidInventory,
                                  allocation_list.create_all)
        # Confirm that the resource class string, not index, is in
        # the exception and resource providers are listed by uuid.
        self.assertIn(rp1_class, str(error))
        self.assertIn(rp2_class, str(error))
        self.assertIn(rp1.uuid, str(error))
        self.assertIn(rp2.uuid, str(error))

        # Add inventory for one of the two resource providers. This should also
        # fail, since rp2 has no inventory.
        inv = objects.Inventory(resource_provider=rp1,
                                resource_class=rp1_class,
                                total=1024)
        inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv])
        rp1.set_inventory(inv_list)
        self.assertRaises(exception.InvalidInventory,
                          allocation_list.create_all)

        # Add inventory for the second resource provider
        inv = objects.Inventory(resource_provider=rp2,
                                resource_class=rp2_class,
                                total=255, reserved=2)
        inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv])
        rp2.set_inventory(inv_list)

        # Now the allocations will still fail because max_unit 1
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          allocation_list.create_all)
        inv1 = objects.Inventory(resource_provider=rp1,
                                resource_class=rp1_class,
                                total=1024, max_unit=max_unit)
        inv1.obj_set_defaults()
        rp1.set_inventory(objects.InventoryList(objects=[inv1]))
        inv2 = objects.Inventory(resource_provider=rp2,
                                resource_class=rp2_class,
                                total=255, reserved=2, max_unit=max_unit)
        inv2.obj_set_defaults()
        rp2.set_inventory(objects.InventoryList(objects=[inv2]))

        # Now we can finally allocate.
        allocation_list.create_all()

        # Check that those allocations changed usage on each
        # resource provider.
        rp1_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp1_uuid)
        rp2_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp2_uuid)
        self.assertEqual(rp1_used, rp1_usage[0].usage)
        self.assertEqual(rp2_used, rp2_usage[0].usage)

        # redo one allocation
        # TODO(cdent): This does not currently behave as expected
        # because a new allocataion is created, adding to the total
        # used, not replacing.
        rp1_used += 1
        allocation_1 = objects.Allocation(resource_provider=rp1,
                                          consumer_id=consumer_uuid,
                                          resource_class=rp1_class,
                                          used=rp1_used)
        allocation_list = objects.AllocationList(
            self.context, objects=[allocation_1])
        allocation_list.create_all()

        rp1_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp1_uuid)
        self.assertEqual(rp1_used, rp1_usage[0].usage)

        # delete the allocations for the consumer
        # NOTE(cdent): The database uses 'consumer_id' for the
        # column, presumably because some ids might not be uuids, at
        # some point in the future.
        consumer_allocations = objects.AllocationList.get_all_by_consumer_id(
            self.context, consumer_uuid)
        consumer_allocations.delete_all()

        rp1_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp1_uuid)
        rp2_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp2_uuid)
        self.assertEqual(0, rp1_usage[0].usage)
        self.assertEqual(0, rp2_usage[0].usage)

    def _make_rp_and_inventory(self, **kwargs):
        # Create one resource provider and set some inventory
        rp_name = uuidsentinel.rp_name
        rp_uuid = uuidsentinel.rp_uuid
        rp = objects.ResourceProvider(
            self.context, name=rp_name, uuid=rp_uuid)
        rp.create()
        inv = objects.Inventory(resource_provider=rp,
                                total=1024, allocation_ratio=1,
                                reserved=0, **kwargs)
        inv.obj_set_defaults()
        rp.set_inventory(objects.InventoryList(objects=[inv]))
        return rp

    def _validate_usage(self, rp, usage):
        rp_usage = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(usage, rp_usage[0].usage)

    def _check_create_allocations(self, inventory_kwargs,
                                  bad_used, good_used):
        consumer_uuid = uuidsentinel.consumer
        rp_class = fields.ResourceClass.DISK_GB
        rp = self._make_rp_and_inventory(resource_class=rp_class,
                                         **inventory_kwargs)

        # allocation, bad step_size
        allocation = objects.Allocation(resource_provider=rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        used=bad_used)
        allocation_list = objects.AllocationList(self.context,
                                                 objects=[allocation])
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          allocation_list.create_all)

        # correct for step size
        allocation.used = good_used
        allocation_list = objects.AllocationList(self.context,
                                                 objects=[allocation])
        allocation_list.create_all()

        # check usage
        self._validate_usage(rp, allocation.used)

    def test_create_all_step_size(self):
        bad_used = 4
        good_used = 5
        inventory_kwargs = {'max_unit': 9999, 'step_size': 5}

        self._check_create_allocations(inventory_kwargs,
                                       bad_used, good_used)

    def test_create_all_min_unit(self):
        bad_used = 4
        good_used = 5
        inventory_kwargs = {'max_unit': 9999, 'min_unit': 5}

        self._check_create_allocations(inventory_kwargs,
                                       bad_used, good_used)

    def test_create_all_max_unit(self):
        bad_used = 5
        good_used = 3
        inventory_kwargs = {'max_unit': 3}

        self._check_create_allocations(inventory_kwargs,
                                       bad_used, good_used)


class UsageListTestCase(ResourceProviderBaseCase):

    def test_get_all_null(self):
        for uuid in [uuidsentinel.rp_uuid_1, uuidsentinel.rp_uuid_2]:
            rp = objects.ResourceProvider(self.context, name=uuid, uuid=uuid)
            rp.create()

        usage_list = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, uuidsentinel.rp_uuid_1)
        self.assertEqual(0, len(usage_list))

    def test_get_all_one_allocation(self):
        db_rp, _ = self._make_allocation(rp_uuid=uuidsentinel.rp_uuid)
        inv = objects.Inventory(resource_provider=db_rp,
                                resource_class=fields.ResourceClass.DISK_GB,
                                total=1024)
        inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv])
        db_rp.set_inventory(inv_list)

        usage_list = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, db_rp.uuid)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(2, usage_list[0].usage)
        self.assertEqual(fields.ResourceClass.DISK_GB,
                         usage_list[0].resource_class)

    def test_get_inventory_no_allocation(self):
        db_rp = objects.ResourceProvider(self.context,
                                         name=uuidsentinel.rp_no_inv,
                                         uuid=uuidsentinel.rp_no_inv)
        db_rp.create()
        inv = objects.Inventory(resource_provider=db_rp,
                                resource_class=fields.ResourceClass.DISK_GB,
                                total=1024)
        inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv])
        db_rp.set_inventory(inv_list)

        usage_list = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, db_rp.uuid)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(0, usage_list[0].usage)
        self.assertEqual(fields.ResourceClass.DISK_GB,
                         usage_list[0].resource_class)

    def test_get_all_multiple_inv(self):
        db_rp = objects.ResourceProvider(self.context,
                                         name=uuidsentinel.rp_no_inv,
                                         uuid=uuidsentinel.rp_no_inv)
        db_rp.create()
        disk_inv = objects.Inventory(
            resource_provider=db_rp,
            resource_class=fields.ResourceClass.DISK_GB, total=1024)
        disk_inv.obj_set_defaults()
        vcpu_inv = objects.Inventory(
            resource_provider=db_rp,
            resource_class=fields.ResourceClass.VCPU, total=24)
        vcpu_inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[disk_inv, vcpu_inv])
        db_rp.set_inventory(inv_list)

        usage_list = objects.UsageList.get_all_by_resource_provider_uuid(
            self.context, db_rp.uuid)
        self.assertEqual(2, len(usage_list))


class ResourceClassListTestCase(ResourceProviderBaseCase):

    def test_get_all_no_custom(self):
        """Test that if we haven't yet added any custom resource classes, that
        we only get a list of ResourceClass objects representing the standard
        classes.
        """
        rcs = objects.ResourceClassList.get_all(self.context)
        self.assertEqual(len(fields.ResourceClass.STANDARD), len(rcs))

    def test_get_all_with_custom(self):
        """Test that if we add some custom resource classes, that we get a list
        of ResourceClass objects representing the standard classes as well as
        the custom classes.
        """
        customs = [
            ('CUSTOM_IRON_NFV', 10001),
            ('CUSTOM_IRON_ENTERPRISE', 10002),
        ]
        with self.api_db.get_engine().connect() as conn:
            for custom in customs:
                c_name, c_id = custom
                ins = rp_obj._RC_TBL.insert().values(id=c_id, name=c_name)
                conn.execute(ins)

        rcs = objects.ResourceClassList.get_all(self.context)
        expected_count = len(fields.ResourceClass.STANDARD) + len(customs)
        self.assertEqual(expected_count, len(rcs))


class ResourceClassTestCase(ResourceProviderBaseCase):

    def test_get_by_name(self):
        rc = objects.ResourceClass.get_by_name(
            self.context,
            fields.ResourceClass.VCPU
        )
        vcpu_id = fields.ResourceClass.STANDARD.index(
            fields.ResourceClass.VCPU
        )
        self.assertEqual(vcpu_id, rc.id)
        self.assertEqual(fields.ResourceClass.VCPU, rc.name)

    def test_get_by_name_not_found(self):
        self.assertRaises(exception.ResourceClassNotFound,
                          objects.ResourceClass.get_by_name,
                          self.context,
                          'CUSTOM_NO_EXISTS')

    def test_get_by_name_custom(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        get_rc = objects.ResourceClass.get_by_name(
            self.context,
            'CUSTOM_IRON_NFV',
        )
        self.assertEqual(rc.id, get_rc.id)
        self.assertEqual(rc.name, get_rc.name)

    def test_create_fail_not_using_namespace(self):
        rc = objects.ResourceClass(
            context=self.context,
            name='IRON_NFV',
        )
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('name must start with', str(exc))

    def test_create_duplicate_standard(self):
        rc = objects.ResourceClass(
            context=self.context,
            name=fields.ResourceClass.VCPU,
        )
        self.assertRaises(exception.ResourceClassExists, rc.create)

    def test_create(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        min_id = objects.ResourceClass.MIN_CUSTOM_RESOURCE_CLASS_ID
        self.assertEqual(min_id, rc.id)

        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_ENTERPRISE',
        )
        rc.create()
        self.assertEqual(min_id + 1, rc.id)

    @mock.patch.object(nova.objects.ResourceClass, "_get_next_id")
    def test_create_duplicate_id_retry(self, mock_get):
        # This order of ID generation will create rc1 with an ID of 42, try to
        # create rc2 with the same ID, and then return 43 in the retry loop.
        mock_get.side_effect = (42, 42, 43)
        rc1 = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc1.create()
        rc2 = objects.ResourceClass(
            self.context,
            name='CUSTOM_TWO',
        )
        rc2.create()
        self.assertEqual(rc1.id, 42)
        self.assertEqual(rc2.id, 43)

    @mock.patch.object(nova.objects.ResourceClass, "_get_next_id")
    def test_create_duplicate_id_retry_failing(self, mock_get):
        """negative case for test_create_duplicate_id_retry"""
        # This order of ID generation will create rc1 with an ID of 44, try to
        # create rc2 with the same ID, and then return 45 in the retry loop.
        mock_get.side_effect = (44, 44, 44, 44)
        rc1 = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc1.create()
        rc2 = objects.ResourceClass(
            self.context,
            name='CUSTOM_TWO',
        )
        rc2.RESOURCE_CREATE_RETRY_COUNT = 3
        self.assertRaises(exception.MaxDBRetriesExceeded, rc2.create)

    def test_create_duplicate_custom(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        self.assertEqual(objects.ResourceClass.MIN_CUSTOM_RESOURCE_CLASS_ID,
                         rc.id)
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ResourceClassExists, rc.create)

    def test_destroy_fail_no_id(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ObjectActionError, rc.destroy)

    def test_destroy_fail_standard(self):
        rc = objects.ResourceClass.get_by_name(
            self.context,
            'VCPU',
        )
        self.assertRaises(exception.ResourceClassCannotDeleteStandard,
                          rc.destroy)

    def test_destroy(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        rc_list = objects.ResourceClassList.get_all(self.context)
        rc_ids = (r.id for r in rc_list)
        self.assertIn(rc.id, rc_ids)

        rc = objects.ResourceClass.get_by_name(
            self.context,
            'CUSTOM_IRON_NFV',
        )

        rc.destroy()
        rc_list = objects.ResourceClassList.get_all(self.context)
        rc_ids = (r.id for r in rc_list)
        self.assertNotIn(rc.id, rc_ids)

        # Verify rc cache was purged of the old entry
        self.assertRaises(exception.ResourceClassNotFound,
                          objects.ResourceClass.get_by_name,
                          self.context,
                          'CUSTOM_IRON_NFV')

    def test_destroy_fail_with_inventory(self):
        """Test that we raise an exception when attempting to delete a resource
        class that is referenced in an inventory record.
        """
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        rp = objects.ResourceProvider(
            self.context,
            name='my rp',
            uuid=uuidsentinel.rp,
        )
        rp.create()
        inv = objects.Inventory(
            resource_provider=rp,
            resource_class='CUSTOM_IRON_NFV',
            total=1,
        )
        inv.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[inv])
        rp.set_inventory(inv_list)

        self.assertRaises(exception.ResourceClassInUse,
                          rc.destroy)

        rp.set_inventory(objects.InventoryList(objects=[]))
        rc.destroy()
        rc_list = objects.ResourceClassList.get_all(self.context)
        rc_ids = (r.id for r in rc_list)
        self.assertNotIn(rc.id, rc_ids)

    def test_save_fail_no_id(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ObjectActionError, rc.save)

    def test_save_fail_standard(self):
        rc = objects.ResourceClass.get_by_name(
            self.context,
            'VCPU',
        )
        self.assertRaises(exception.ResourceClassCannotUpdateStandard,
                          rc.save)

    def test_save(self):
        rc = objects.ResourceClass(
            self.context,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()

        rc = objects.ResourceClass.get_by_name(
            self.context,
            'CUSTOM_IRON_NFV',
        )
        rc.name = 'CUSTOM_IRON_SILVER'
        rc.save()

        # Verify rc cache was purged of the old entry
        self.assertRaises(exception.NotFound,
                          objects.ResourceClass.get_by_name,
                          self.context,
                          'CUSTOM_IRON_NFV')


class ResourceProviderTraitTestCase(ResourceProviderBaseCase):

    def _assert_traits(self, expected_traits, traits_objs):
        expected_traits.sort()
        traits = []
        for obj in traits_objs:
            traits.append(obj.name)
        traits.sort()
        self.assertEqual(expected_traits, traits)

    def test_trait_create(self):
        t = objects.Trait(self.context)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        self.assertIn('id', t)
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')

    def test_trait_create_with_id_set(self):
        t = objects.Trait(self.context)
        t.name = 'CUSTOM_TRAIT_A'
        t.id = 1
        self.assertRaises(exception.ObjectActionError, t.create)

    def test_trait_create_without_name_set(self):
        t = objects.Trait(self.context)
        self.assertRaises(exception.ObjectActionError, t.create)

    def test_trait_create_duplicated_trait(self):
        trait = objects.Trait(self.context)
        trait.name = 'CUSTOM_TRAIT_A'
        trait.create()
        tmp_trait = objects.Trait.get_by_name(self.context, 'CUSTOM_TRAIT_A')
        self.assertEqual('CUSTOM_TRAIT_A', tmp_trait.name)
        duplicated_trait = objects.Trait(self.context)
        duplicated_trait.name = 'CUSTOM_TRAIT_A'
        self.assertRaises(exception.TraitExists, duplicated_trait.create)

    def test_trait_get(self):
        t = objects.Trait(self.context)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        t = objects.Trait.get_by_name(self.context, 'CUSTOM_TRAIT_A')
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')

    def test_trait_get_non_existed_trait(self):
        self.assertRaises(exception.TraitNotFound,
            objects.Trait.get_by_name, self.context, 'CUSTOM_TRAIT_A')

    def test_trait_destroy(self):
        t = objects.Trait(self.context)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        t = objects.Trait.get_by_name(self.context, 'CUSTOM_TRAIT_A')
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')
        t.destroy()
        self.assertRaises(exception.TraitNotFound, objects.Trait.get_by_name,
                          self.context, 'CUSTOM_TRAIT_A')

    def test_trait_destroy_with_standard_trait(self):
        t = objects.Trait(self.context)
        t.id = 1
        t.name = 'HW_CPU_X86_AVX'
        self.assertRaises(exception.TraitCannotDeleteStandard, t.destroy)

    def test_traits_get_all(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()

        self._assert_traits(trait_names,
                            objects.TraitList.get_all(self.context))

    def test_traits_get_all_with_name_in_filter(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()

        traits = objects.TraitList.get_all(self.context,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        self._assert_traits(['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B'], traits)

    def test_traits_get_all_with_non_existed_name(self):
        traits = objects.TraitList.get_all(self.context,
            filters={'name_in': ['CUSTOM_TRAIT_X', 'CUSTOM_TRAIT_Y']})
        self.assertEqual(0, len(traits))

    def test_traits_get_all_with_prefix_filter(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()

        traits = objects.TraitList.get_all(self.context,
                                           filters={'prefix': 'CUSTOM'})
        self._assert_traits(
            ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C'],
            traits)

    def test_traits_get_all_with_non_existed_prefix(self):
        traits = objects.TraitList.get_all(self.context,
            filters={"prefix": "NOT_EXISTED"})
        self.assertEqual(0, len(traits))

    def test_set_traits_for_resource_provider(self):
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        rp.create()
        generation = rp.generation
        self.assertIsInstance(rp.id, int)

        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        trait_objs = []
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()
            trait_objs.append(t)

        rp.set_traits(trait_objs)
        self._assert_traits(trait_names, rp.get_traits())
        self.assertEqual(rp.generation, generation + 1)
        generation = rp.generation

        trait_names.remove('CUSTOM_TRAIT_A')
        updated_traits = objects.TraitList.get_all(self.context,
            filters={'name_in': trait_names})
        self._assert_traits(trait_names, updated_traits)
        rp.set_traits(updated_traits)
        self._assert_traits(trait_names, rp.get_traits())
        self.assertEqual(rp.generation, generation + 1)

    def test_trait_delete_in_use(self):
        rp = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        rp.create()
        t = objects.Trait(self.context)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        rp.set_traits([t])
        self.assertRaises(exception.TraitInUse, t.destroy)

    def test_traits_get_all_with_associated_true(self):
        rp1 = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider1,
            name=uuidsentinel.fake_resource_name1,
        )
        rp1.create()
        rp2 = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider2,
            name=uuidsentinel.fake_resource_name2,
        )
        rp2.create()
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()

        associated_traits = objects.TraitList.get_all(self.context,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        rp1.set_traits(associated_traits)
        rp2.set_traits(associated_traits)
        self._assert_traits(['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B'],
            objects.TraitList.get_all(self.context,
                filters={'associated': True}))

    def test_traits_get_all_with_associated_false(self):
        rp1 = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider1,
            name=uuidsentinel.fake_resource_name1,
        )
        rp1.create()
        rp2 = objects.ResourceProvider(
            context=self.context,
            uuid=uuidsentinel.fake_resource_provider2,
            name=uuidsentinel.fake_resource_name2,
        )
        rp2.create()
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = objects.Trait(self.context)
            t.name = name
            t.create()

        associated_traits = objects.TraitList.get_all(self.context,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        rp1.set_traits(associated_traits)
        rp2.set_traits(associated_traits)
        self._assert_traits(['CUSTOM_TRAIT_C'],
            objects.TraitList.get_all(self.context,
                filters={'associated': False}))


class SharedProviderTestCase(ResourceProviderBaseCase):
    """Tests that the queries used to determine placement in deployments with
    shared resource providers such as a shared disk pool result in accurate
    reporting of inventory and usage.
    """

    def test_shared_provider_capacity(self):
        """Sets up a resource provider that shares DISK_GB inventory via an
        aggregate, a couple resource providers representing "local disk"
        compute nodes and ensures the _get_providers_sharing_capacity()
        function finds that provider and not providers of "local disk".
        """
        # Create the two "local disk" compute node providers
        cn1_uuid = uuidsentinel.cn1
        cn1 = objects.ResourceProvider(
            self.context,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = objects.ResourceProvider(
            self.context,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        # Populate the two compute node providers with inventory, sans DISK_GB
        for cn in (cn1, cn2):
            vcpu = objects.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = objects.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=32768,
                reserved=0,
                min_unit=64,
                max_unit=32768,
                step_size=64,
                allocation_ratio=1.5,
            )
            inv_list = objects.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the shared storage pool
        ss_uuid = uuidsentinel.ss
        ss = objects.ResourceProvider(
            self.context,
            name='shared storage',
            uuid=ss_uuid,
        )
        ss.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = objects.Inventory(
            resource_provider=ss,
            resource_class=fields.ResourceClass.DISK_GB,
            total=2000,
            reserved=0,
            min_unit=10,
            max_unit=100,
            step_size=10,
            allocation_ratio=1.0,
        )
        disk_gb.obj_set_defaults()
        inv_list = objects.InventoryList(objects=[disk_gb])
        ss.set_inventory(inv_list)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        t = objects.Trait(
            self.context,
            name="MISC_SHARES_VIA_AGGREGATE",
        )
        # TODO(jaypipes): Once MISC_SHARES_VIA_AGGREGATE is a standard
        # os-traits trait, we won't need to create() here. Instead, we will
        # just do:
        # t = objects.Trait.get_by_name(
        #    self.context,
        #    "MISC_SHARES_VIA_AGGREGATE",
        # )
        t.create()
        ss.set_traits(objects.TraitList(objects=[t]))

        # OK, now that has all been set up, let's verify that we get the ID of
        # the shared storage pool when we ask for 100 DISK_GB
        got_ids = rp_obj._get_providers_with_shared_capacity(
            self.context,
            fields.ResourceClass.STANDARD.index(fields.ResourceClass.DISK_GB),
            100,
        )
        self.assertEqual([ss.id], got_ids)
