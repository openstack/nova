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


import functools
import mock
import os_traits
from oslo_db import exception as db_exc
import sqlalchemy as sa

import nova
from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.db.sqlalchemy import api_models as models
from nova import rc_fields as fields
from nova.tests.functional.api.openstack.placement.db import test_base as tb
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


class ResourceProviderTestCase(tb.PlacementDbBaseTestCase):
    """Test resource-provider objects' lifecycles."""

    def test_provider_traits_empty_param(self):
        self.assertRaises(ValueError, rp_obj._get_traits_by_provider_tree,
                          self.ctx, [])

    def test_trait_ids_from_names_empty_param(self):
        self.assertRaises(ValueError, rp_obj._trait_ids_from_names,
                          self.ctx, [])

    def test_create_resource_provider_requires_uuid(self):
        resource_provider = rp_obj.ResourceProvider(
            context = self.ctx)
        self.assertRaises(exception.ObjectActionError,
                          resource_provider.create)

    def test_create_unknown_parent_provider(self):
        """Test that if we provide a parent_provider_uuid value that points to
        a resource provider that doesn't exist, that we get an
        ObjectActionError.
        """
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            name='rp1',
            uuid=uuidsentinel.rp1,
            parent_provider_uuid=uuidsentinel.noexists)
        exc = self.assertRaises(exception.ObjectActionError, rp.create)
        self.assertIn('parent provider UUID does not exist', str(exc))

    def test_create_with_parent_provider_uuid_same_as_uuid_fail(self):
        """Setting a parent provider UUID to one's own UUID makes no sense, so
        check we don't support it.
        """
        cn1 = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.cn1, name='cn1',
            parent_provider_uuid=uuidsentinel.cn1)

        exc = self.assertRaises(exception.ObjectActionError, cn1.create)
        self.assertIn('parent provider UUID cannot be same as UUID', str(exc))

    def test_create_resource_provider(self):
        created_resource_provider = self._create_provider(
            uuidsentinel.fake_resource_name,
            uuid=uuidsentinel.fake_resource_provider,
        )
        self.assertIsInstance(created_resource_provider.id, int)

        retrieved_resource_provider = rp_obj.ResourceProvider.get_by_uuid(
            self.ctx,
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
        self.assertIsNone(retrieved_resource_provider.parent_provider_uuid)

    def test_create_with_parent_provider_uuid(self):
        self._create_provider('p1', uuid=uuidsentinel.create_p)
        child = self._create_provider('c1', uuid=uuidsentinel.create_c,
                                      parent=uuidsentinel.create_p)
        self.assertEqual(uuidsentinel.create_c, child.uuid)
        self.assertEqual(uuidsentinel.create_p, child.parent_provider_uuid)
        self.assertEqual(uuidsentinel.create_p, child.root_provider_uuid)

    def test_root_provider_population(self):
        """Simulate an old resource provider record in the database that has no
        root_provider_uuid set and ensure that when grabbing the resource
        provider object, the root_provider_uuid field in the table is set to
        the provider's UUID.
        """
        rp_tbl = rp_obj._RP_TBL
        conn = self.placement_db.get_engine().connect()

        # First, set up a record for an "old-style" resource provider with no
        # root provider UUID.
        ins_stmt = rp_tbl.insert().values(
            id=1,
            uuid=uuidsentinel.rp1,
            name='rp-1',
            root_provider_id=None,
            parent_provider_id=None,
            generation=42,
        )
        conn.execute(ins_stmt)

        rp = rp_obj.ResourceProvider.get_by_uuid(self.ctx, uuidsentinel.rp1)

        # The ResourceProvider._from_db_object() method should have performed
        # an online data migration, populating the root_provider_id field
        # with the value of the id field. Let's check it happened.
        sel_stmt = sa.select([rp_tbl.c.root_provider_id]).where(
            rp_tbl.c.id == 1)
        res = conn.execute(sel_stmt).fetchall()
        self.assertEqual(1, res[0][0])
        # Make sure the object root_provider_uuid is set on load
        self.assertEqual(rp.root_provider_uuid, uuidsentinel.rp1)

    def test_inherit_root_from_parent(self):
        """Tests that if we update an existing provider's parent provider UUID,
        that the root provider UUID of the updated provider is automatically
        set to the parent provider's root provider UUID.
        """
        rp1 = self._create_provider('rp1')

        # Test the root was auto-set to the create provider's UUID
        self.assertEqual(uuidsentinel.rp1, rp1.root_provider_uuid)

        # Create a new provider that we will make the parent of rp1
        parent_rp = self._create_provider('parent')
        self.assertEqual(uuidsentinel.parent, parent_rp.root_provider_uuid)

        # Now change rp1 to be a child of parent and check rp1's root is
        # changed to that of the parent.
        rp1.parent_provider_uuid = parent_rp.uuid
        rp1.save()

        self.assertEqual(uuidsentinel.parent, rp1.root_provider_uuid)

    def test_save_root_provider_failed(self):
        """Test that if we provide a root_provider_uuid value that points to
        a resource provider that doesn't exist, we get an ObjectActionError if
        we save the object.
        """
        self.assertRaises(
            exception.ObjectActionError,
            self._create_provider, 'rp1', root=uuidsentinel.noexists)

    def test_save_unknown_parent_provider(self):
        """Test that if we provide a parent_provider_uuid value that points to
        a resource provider that doesn't exist, that we get an
        ObjectActionError if we save the object.
        """
        self.assertRaises(
            exception.ObjectActionError,
            self._create_provider, 'rp1', parent=uuidsentinel.noexists)

    def test_save_resource_provider(self):
        created_resource_provider = self._create_provider(
            uuidsentinel.fake_resource_name,
            uuid=uuidsentinel.fake_resource_provider,
        )
        created_resource_provider.name = 'new-name'
        created_resource_provider.save()
        retrieved_resource_provider = rp_obj.ResourceProvider.get_by_uuid(
            self.ctx,
            uuidsentinel.fake_resource_provider
        )
        self.assertEqual('new-name', retrieved_resource_provider.name)

    def test_save_reparenting_fail(self):
        """Tests that we prevent a resource provider's parent provider UUID
        from being changed from a non-NULL value to another non-NULL value.
        """
        cn1 = self._create_provider('cn1')
        self._create_provider('cn2')
        self._create_provider('cn3')

        # First, make sure we can set the parent for a provider that does not
        # have a parent currently
        cn1.parent_provider_uuid = uuidsentinel.cn2
        cn1.save()

        # Now make sure we can't change the parent provider
        cn1.parent_provider_uuid = uuidsentinel.cn3
        exc = self.assertRaises(exception.ObjectActionError, cn1.save)
        self.assertIn('re-parenting a provider is not currently', str(exc))

        # Also ensure that we can't "un-parent" a provider
        cn1.parent_provider_uuid = None
        exc = self.assertRaises(exception.ObjectActionError, cn1.save)
        self.assertIn('un-parenting a provider is not currently', str(exc))

    def test_nested_providers(self):
        """Create a hierarchy of resource providers and run through a series of
        tests that ensure one cannot delete a resource provider that has no
        direct allocations but its child providers do have allocations.
        """
        root_rp = self._create_provider('root_rp')
        child_rp = self._create_provider('child_rp',
                                         parent=uuidsentinel.root_rp)
        grandchild_rp = self._create_provider('grandchild_rp',
                                              parent=uuidsentinel.child_rp)

        # Verify that the root_provider_uuid of both the child and the
        # grandchild is the UUID of the grandparent
        self.assertEqual(root_rp.uuid, child_rp.root_provider_uuid)
        self.assertEqual(root_rp.uuid, grandchild_rp.root_provider_uuid)

        # Create some inventory in the grandchild, allocate some consumers to
        # the grandchild and then attempt to delete the root provider and child
        # provider, both of which should fail.
        tb.add_inventory(grandchild_rp, fields.ResourceClass.VCPU, 1)

        # Check all providers returned when getting by root UUID
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.root_rp,
            }
        )
        self.assertEqual(3, len(rps))

        # Check all providers returned when getting by child UUID
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.child_rp,
            }
        )
        self.assertEqual(3, len(rps))

        # Check all providers returned when getting by grandchild UUID
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.grandchild_rp,
            }
        )
        self.assertEqual(3, len(rps))

        # Make sure that the member_of and uuid filters work with the in_tree
        # filter

        # No aggregate associations yet, so expect no records when adding a
        # member_of filter
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'member_of': [[uuidsentinel.agg]],
                'in_tree': uuidsentinel.grandchild_rp,
            }
        )
        self.assertEqual(0, len(rps))

        # OK, associate the grandchild with an aggregate and verify that ONLY
        # the grandchild is returned when asking for the grandchild's tree
        # along with the aggregate as member_of
        grandchild_rp.set_aggregates([uuidsentinel.agg])
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'member_of': [[uuidsentinel.agg]],
                'in_tree': uuidsentinel.grandchild_rp,
            }
        )
        self.assertEqual(1, len(rps))
        self.assertEqual(uuidsentinel.grandchild_rp, rps[0].uuid)

        # Try filtering on an unknown UUID and verify no results
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'uuid': uuidsentinel.unknown_rp,
                'in_tree': uuidsentinel.grandchild_rp,
            }
        )
        self.assertEqual(0, len(rps))

        # And now check that filtering for just the child's UUID along with the
        # tree produces just a single provider (the child)
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'uuid': uuidsentinel.child_rp,
                'in_tree': uuidsentinel.grandchild_rp,
            }
        )
        self.assertEqual(1, len(rps))
        self.assertEqual(uuidsentinel.child_rp, rps[0].uuid)

        # Ensure that the resources filter also continues to work properly with
        # the in_tree filter. Request resources that none of the providers
        # currently have and ensure no providers are returned
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.grandchild_rp,
                'resources': {
                    'VCPU': 200,
                }
            }
        )
        self.assertEqual(0, len(rps))

        # And now ask for one VCPU, which should only return us the grandchild
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.grandchild_rp,
                'resources': {
                    'VCPU': 1,
                }
            }
        )
        self.assertEqual(1, len(rps))
        self.assertEqual(uuidsentinel.grandchild_rp, rps[0].uuid)

        # Finally, verify we still get the grandchild if filtering on the
        # parent's UUID as in_tree
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.child_rp,
                'resources': {
                    'VCPU': 1,
                }
            }
        )
        self.assertEqual(1, len(rps))
        self.assertEqual(uuidsentinel.grandchild_rp, rps[0].uuid)

        alloc_list = self.allocate_from_provider(
            grandchild_rp, fields.ResourceClass.VCPU, 1)

        self.assertRaises(exception.CannotDeleteParentResourceProvider,
                          root_rp.destroy)
        self.assertRaises(exception.CannotDeleteParentResourceProvider,
                          child_rp.destroy)

        # Cannot delete provider if it has allocations
        self.assertRaises(exception.ResourceProviderInUse,
                          grandchild_rp.destroy)

        # Now remove the allocations against the child and check that we can
        # now delete the child provider
        alloc_list.delete_all()
        grandchild_rp.destroy()
        child_rp.destroy()
        root_rp.destroy()

    def test_get_all_in_tree_old_records(self):
        """Simulate an old resource provider record in the database that has no
        root_provider_uuid set and ensure that when selecting all providers in
        a tree, passing in that old resource provider, that we still get that
        provider returned.
        """
        # Passing a non-existing resource provider UUID should return an empty
        # list
        rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={
                'in_tree': uuidsentinel.rp1,
            }
        )
        self.assertEqual([], rps.objects)

        rp_tbl = rp_obj._RP_TBL
        conn = self.placement_db.get_engine().connect()

        # First, set up a record for an "old-style" resource provider with no
        # root provider UUID.
        ins_stmt = rp_tbl.insert().values(
            id=1,
            uuid=uuidsentinel.rp1,
            name='rp-1',
            root_provider_id=None,
            parent_provider_id=None,
            generation=42,
        )
        conn.execute(ins_stmt)

        # NOTE(jaypipes): This is just disabling the online data migration that
        # occurs in _from_db_object() that sets root provider ID to ensure we
        # don't have any migrations messing with the end result.
        with mock.patch('nova.api.openstack.placement.objects.'
                        'resource_provider._set_root_provider_id'):
            rps = rp_obj.ResourceProviderList.get_all_by_filters(
                self.ctx,
                filters={
                    'in_tree': uuidsentinel.rp1,
                }
            )
        self.assertEqual(1, len(rps))

    def test_has_provider_trees(self):
        """The _has_provider_trees() helper method should return False unless
        there is a resource provider that is a parent.
        """
        self.assertFalse(rp_obj._has_provider_trees(self.ctx))
        self._create_provider('cn')

        # No parents yet. Should still be False.
        self.assertFalse(rp_obj._has_provider_trees(self.ctx))

        self._create_provider('numa0', parent=uuidsentinel.cn)

        # OK, now we've got a parent, so should be True
        self.assertTrue(rp_obj._has_provider_trees(self.ctx))

    def test_destroy_resource_provider(self):
        created_resource_provider = self._create_provider(
            uuidsentinel.fake_resource_name,
            uuid=uuidsentinel.fake_resource_provider,
        )
        created_resource_provider.destroy()
        self.assertRaises(exception.NotFound,
                          rp_obj.ResourceProvider.get_by_uuid,
                          self.ctx,
                          uuidsentinel.fake_resource_provider)
        self.assertRaises(exception.NotFound,
                          created_resource_provider.destroy)

    def test_destroy_foreign_key(self):
        """This tests bug #1739571."""

        def emulate_rp_mysql_delete(func):
            def wrapped(context, _id):
                rp = context.session.query(
                    models.ResourceProvider).\
                    filter(
                        models.ResourceProvider.id == _id).first()
                self.assertIsNone(rp.root_provider_id)
                return func(context, _id)
            return wrapped

        emulated = emulate_rp_mysql_delete(rp_obj._delete_rp_record)

        rp = self._create_provider(uuidsentinel.fk)

        with mock.patch.object(rp_obj, '_delete_rp_record', emulated):
            rp.destroy()

    def test_destroy_allocated_resource_provider_fails(self):
        rp, allocation = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)
        self.assertRaises(exception.ResourceProviderInUse,
                          rp.destroy)

    def test_destroy_resource_provider_destroy_inventory(self):
        resource_provider = self._create_provider(
            uuidsentinel.fake_resource_name,
            uuid=uuidsentinel.fake_resource_provider,
        )
        tb.add_inventory(resource_provider, DISK_INVENTORY['resource_class'],
                         DISK_INVENTORY['total'])
        inventories = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, resource_provider)
        self.assertEqual(1, len(inventories))
        resource_provider.destroy()
        inventories = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, resource_provider)
        self.assertEqual(0, len(inventories))

    def test_destroy_with_traits(self):
        """Test deleting a resource provider that has a trait successfully.
        """
        rp = self._create_provider('fake_rp1', uuid=uuidsentinel.fake_rp1)
        custom_trait = 'CUSTOM_TRAIT_1'
        tb.set_traits(rp, custom_trait)

        trl = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self.assertEqual(1, len(trl))

        # Delete a resource provider that has a trait assosiation.
        rp.destroy()

        # Assert the record has been deleted
        # in 'resource_provider_traits' table
        # after Resource Provider object has been destroyed.
        trl = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self.assertEqual(0, len(trl))
        # Assert that NotFound exception is raised.
        self.assertRaises(exception.NotFound,
                          rp_obj.ResourceProvider.get_by_uuid,
                          self.ctx, uuidsentinel.fake_rp1)

    def test_set_inventory_unknown_resource_class(self):
        """Test attempting to set inventory to an unknown resource class raises
        an exception.
        """
        rp = self._create_provider('compute-host')
        self.assertRaises(exception.ResourceClassNotFound,
                          tb.add_inventory, rp, 'UNKNOWN', 1024,
                          reserved=15,
                          min_unit=10,
                          max_unit=100,
                          step_size=10,
                          allocation_ratio=1.0)

    def test_set_inventory_fail_in_use(self):
        """Test attempting to set inventory which would result in removing an
        inventory record for a resource class that still has allocations
        against it.
        """
        rp = self._create_provider('compute-host')
        tb.add_inventory(rp, 'VCPU', 12)
        self.allocate_from_provider(rp, 'VCPU', 1)

        inv = rp_obj.Inventory(
            resource_provider=rp,
            resource_class='MEMORY_MB',
            total=1024,
            reserved=0,
            min_unit=256,
            max_unit=1024,
            step_size=256,
            allocation_ratio=1.0,
        )

        inv_list = rp_obj.InventoryList(objects=[inv])
        self.assertRaises(exception.InventoryInUse,
                          rp.set_inventory,
                          inv_list)

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.LOG')
    def test_set_inventory_over_capacity(self, mock_log):
        rp = self._create_provider(uuidsentinel.rp_name)

        disk_inv = tb.add_inventory(rp, fields.ResourceClass.DISK_GB, 2048,
                                    reserved=15,
                                    min_unit=10,
                                    max_unit=600,
                                    step_size=10)
        vcpu_inv = tb.add_inventory(rp, fields.ResourceClass.VCPU, 12,
                                    allocation_ratio=16.0)

        self.assertFalse(mock_log.warning.called)

        # Allocate something reasonable for the above inventory
        self.allocate_from_provider(rp, 'DISK_GB', 500)

        # Update our inventory to over-subscribe us after the above allocation
        disk_inv.total = 400
        rp.set_inventory(rp_obj.InventoryList(objects=[disk_inv, vcpu_inv]))

        # We should succeed, but have logged a warning for going over on disk
        mock_log.warning.assert_called_once_with(
            mock.ANY, {'uuid': rp.uuid, 'resource': 'DISK_GB'})

    def test_provider_modify_inventory(self):
        rp = self._create_provider(uuidsentinel.rp_name)
        saved_generation = rp.generation

        disk_inv = tb.add_inventory(rp, fields.ResourceClass.DISK_GB, 1024,
                                    reserved=15,
                                    min_unit=10,
                                    max_unit=100,
                                    step_size=10)

        vcpu_inv = tb.add_inventory(rp, fields.ResourceClass.VCPU, 12,
                                    allocation_ratio=16.0)

        # generation has bumped once for each add
        self.assertEqual(saved_generation + 2, rp.generation)
        saved_generation = rp.generation

        new_inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
        self.assertEqual(2, len(new_inv_list))
        resource_classes = [inv.resource_class for inv in new_inv_list]
        self.assertIn(fields.ResourceClass.VCPU, resource_classes)
        self.assertIn(fields.ResourceClass.DISK_GB, resource_classes)

        # reset list to just disk_inv
        inv_list = rp_obj.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
        self.assertEqual(1, len(new_inv_list))
        resource_classes = [inv.resource_class for inv in new_inv_list]
        self.assertNotIn(fields.ResourceClass.VCPU, resource_classes)
        self.assertIn(fields.ResourceClass.DISK_GB, resource_classes)
        self.assertEqual(1024, new_inv_list[0].total)

        # update existing disk inv to new settings
        disk_inv = rp_obj.Inventory(
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

        new_inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
        self.assertEqual(1, len(new_inv_list))
        self.assertEqual(2048, new_inv_list[0].total)

        # delete inventory
        rp.delete_inventory(fields.ResourceClass.DISK_GB)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
        saved_generation = rp.generation

        new_inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
        result = new_inv_list.find(fields.ResourceClass.DISK_GB)
        self.assertIsNone(result)
        self.assertRaises(exception.NotFound, rp.delete_inventory,
                          fields.ResourceClass.DISK_GB)

        # check inventory list is empty
        inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
        self.assertEqual(0, len(inv_list))

        # add some inventory
        rp.add_inventory(vcpu_inv)
        inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp)
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
        rp = self._create_provider(uuidsentinel.rp_name)
        error = self.assertRaises(exception.NotFound, rp.delete_inventory,
                                  'DISK_GB')
        self.assertIn('No inventory of class DISK_GB found for delete',
                      str(error))

    def test_delete_inventory_with_allocation(self):
        rp, allocation = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)
        error = self.assertRaises(exception.InventoryInUse,
                                  rp.delete_inventory,
                                  'DISK_GB')
        self.assertIn(
            "Inventory for 'DISK_GB' on resource provider '%s' in use"
            % rp.uuid, str(error))

    def test_update_inventory_not_found(self):
        rp = self._create_provider(uuidsentinel.rp_name)
        disk_inv = rp_obj.Inventory(resource_provider=rp,
                                    resource_class='DISK_GB',
                                    total=2048)
        disk_inv.obj_set_defaults()
        error = self.assertRaises(exception.NotFound, rp.update_inventory,
                                  disk_inv)
        self.assertIn('No inventory of class DISK_GB found',
                      str(error))

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.LOG')
    def test_update_inventory_violates_allocation(self, mock_log):
        # Compute nodes that are reconfigured have to be able to set
        # their inventory to something that violates allocations so
        # we need to make that possible.
        rp, allocation = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)
        # attempt to set inventory to less than currently allocated
        # amounts
        new_total = 1
        disk_inv = rp_obj.Inventory(
            resource_provider=rp,
            resource_class=fields.ResourceClass.DISK_GB, total=new_total)
        disk_inv.obj_set_defaults()
        rp.update_inventory(disk_inv)

        usages = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp.uuid)
        self.assertEqual(allocation.used, usages[0].usage)

        inv_list = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, rp)
        self.assertEqual(new_total, inv_list[0].total)
        mock_log.warning.assert_called_once_with(
            mock.ANY, {'uuid': rp.uuid, 'resource': 'DISK_GB'})

    def test_add_allocation_increments_generation(self):
        rp = self._create_provider(name='foo')
        tb.add_inventory(rp, DISK_INVENTORY['resource_class'],
                         DISK_INVENTORY['total'])
        expected_gen = rp.generation + 1
        self.allocate_from_provider(rp, DISK_ALLOCATION['resource_class'],
                                  DISK_ALLOCATION['used'])
        self.assertEqual(expected_gen, rp.generation)

    def test_get_all_by_resource_provider_multiple_providers(self):
        rp1 = self._create_provider('cn1')
        rp2 = self._create_provider(name='cn2')

        for rp in (rp1, rp2):
            tb.add_inventory(rp, DISK_INVENTORY['resource_class'],
                             DISK_INVENTORY['total'])
            tb.add_inventory(rp, fields.ResourceClass.IPV4_ADDRESS, 10,
                             max_unit=2)

        # Get inventories for the first resource provider and validate
        # the inventory records have a matching resource provider
        got_inv = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp1)
        for inv in got_inv:
            self.assertEqual(rp1.id, inv.resource_provider.id)


class ResourceProviderListTestCase(tb.PlacementDbBaseTestCase):
    def test_get_all_by_filters(self):
        for rp_i in ['1', '2']:
            self._create_provider(
                'rp_name_' + rp_i,
                uuid=getattr(uuidsentinel, 'rp_uuid_' + rp_i))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx)
        self.assertEqual(2, len(resource_providers))
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'uuid': uuidsentinel.rp_uuid_2})
        self.assertEqual(1, len(resource_providers))
        self.assertEqual('rp_name_2', resource_providers[0].name)

    def test_get_all_by_filters_with_resources(self):
        for rp_i in ['1', '2']:
            rp = self._create_provider('rp_name_' + rp_i)
            tb.add_inventory(rp, fields.ResourceClass.VCPU, 2)
            tb.add_inventory(rp, fields.ResourceClass.DISK_GB, 1024,
                             reserved=2)
            # Write a specific inventory for testing min/max units and steps
            tb.add_inventory(rp, fields.ResourceClass.MEMORY_MB, 1024,
                             reserved=2, min_unit=2, max_unit=4, step_size=2)

            # Create the VCPU allocation only for the first RP
            if rp_i != '1':
                continue
            self.allocate_from_provider(rp, fields.ResourceClass.VCPU, used=1)

        # Both RPs should accept that request given the only current allocation
        # for the first RP is leaving one VCPU
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.VCPU: 1}})
        self.assertEqual(2, len(resource_providers))
        # Now, when asking for 2 VCPUs, only the second RP should accept that
        # given the current allocation for the first RP
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.VCPU: 2}})
        self.assertEqual(1, len(resource_providers))
        # Adding a second resource request should be okay for the 2nd RP
        # given it has enough disk but we also need to make sure that the
        # first RP is not acceptable because of the VCPU request
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.VCPU: 2,
                                         fields.ResourceClass.DISK_GB: 1022}})
        self.assertEqual(1, len(resource_providers))
        # Now, we are asking for both disk and VCPU resources that all the RPs
        # can't accept (as the 2nd RP is having a reserved size)
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.VCPU: 2,
                                         fields.ResourceClass.DISK_GB: 1024}})
        self.assertEqual(0, len(resource_providers))

        # We also want to verify that asking for a specific RP can also be
        # checking the resource usage.
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'name': u'rp_name_1',
                       'resources': {fields.ResourceClass.VCPU: 1}})
        self.assertEqual(1, len(resource_providers))

        # Let's verify that the min and max units are checked too
        # Case 1: amount is in between min and max and modulo step_size
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.MEMORY_MB: 2}})
        self.assertEqual(2, len(resource_providers))
        # Case 2: amount is less than min_unit
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.MEMORY_MB: 1}})
        self.assertEqual(0, len(resource_providers))
        # Case 3: amount is more than min_unit
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.MEMORY_MB: 5}})
        self.assertEqual(0, len(resource_providers))
        # Case 4: amount is not modulo step_size
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, {'resources': {fields.ResourceClass.MEMORY_MB: 3}})
        self.assertEqual(0, len(resource_providers))

    def test_get_all_by_filters_with_resources_not_existing(self):
        self.assertRaises(
            exception.ResourceClassNotFound,
            rp_obj.ResourceProviderList.get_all_by_filters,
            self.ctx, {'resources': {'FOOBAR': 3}})

    def test_get_all_by_filters_aggregate(self):
        for rp_i in [1, 2, 3, 4]:
            aggs = [uuidsentinel.agg_a, uuidsentinel.agg_b] if rp_i % 2 else []
            self._create_provider(
                'rp_name_' + str(rp_i), *aggs,
                uuid=getattr(uuidsentinel, 'rp_uuid_' + str(rp_i)))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of': [[uuidsentinel.agg_a]]})

        self.assertEqual(2, len(resource_providers))
        names = [_rp.name for _rp in resource_providers]
        self.assertIn('rp_name_1', names)
        self.assertIn('rp_name_3', names)
        self.assertNotIn('rp_name_2', names)
        self.assertNotIn('rp_name_4', names)

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [[uuidsentinel.agg_a, uuidsentinel.agg_b]]})
        self.assertEqual(2, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [[uuidsentinel.agg_a, uuidsentinel.agg_b]],
                               'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [[uuidsentinel.agg_a, uuidsentinel.agg_b]],
                               'name': u'barnabas'})
        self.assertEqual(0, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [[uuidsentinel.agg_1, uuidsentinel.agg_2]]})
        self.assertEqual(0, len(resource_providers))

    def test_get_all_by_required(self):
        # Create some resource providers and give them each 0 or more traits.
        # rp_name_0: no traits
        # rp_name_1: CUSTOM_TRAIT_A
        # rp_name_2: CUSTOM_TRAIT_A, CUSTOM_TRAIT_B
        # rp_name_3: CUSTOM_TRAIT_A, CUSTOM_TRAIT_B, CUSTOM_TRAIT_C
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B',
                       'CUSTOM_TRAIT_C']
        for rp_i in [0, 1, 2, 3]:
            rp = self._create_provider(
                'rp_name_' + str(rp_i),
                uuid=getattr(uuidsentinel, 'rp_uuid_' + str(rp_i)))
            if rp_i:
                traits = trait_names[0:rp_i]
                tb.set_traits(rp, *traits)

        # Three rps (1, 2, 3) should have CUSTOM_TRAIT_A
        custom_a_rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'required': ['CUSTOM_TRAIT_A']})
        self.assertEqual(3, len(custom_a_rps))
        rp_names = [a_rp.name for a_rp in custom_a_rps]
        expected_names = ['rp_name_%s' % i for i in [1, 2, 3]]
        self.assertEqual(expected_names, sorted(rp_names))

        # One rp (rp 1) if we forbid CUSTOM_TRAIT_B, with a single trait of
        # CUSTOM_TRAIT_A
        custom_a_rps = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx,
            filters={'required': ['CUSTOM_TRAIT_A', '!CUSTOM_TRAIT_B']})
        self.assertEqual(1, len(custom_a_rps))
        self.assertEqual(uuidsentinel.rp_uuid_1, custom_a_rps[0].uuid)
        self.assertEqual('rp_name_1', custom_a_rps[0].name)
        traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, custom_a_rps[0])
        self.assertEqual(1, len(traits))
        self.assertEqual('CUSTOM_TRAIT_A', traits[0].name)


class TestResourceProviderAggregates(tb.PlacementDbBaseTestCase):
    def test_set_and_get_new_aggregates(self):
        aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp = self._create_provider(
            uuidsentinel.rp_name,
            *aggregate_uuids,
            uuid=uuidsentinel.rp_uuid
        )

        read_aggregate_uuids = rp.get_aggregates()
        self.assertItemsEqual(aggregate_uuids, read_aggregate_uuids)

        # Since get_aggregates always does a new query this is
        # mostly nonsense but is here for completeness.
        read_rp = rp_obj.ResourceProvider.get_by_uuid(
            self.ctx, uuidsentinel.rp_uuid)
        re_read_aggregate_uuids = read_rp.get_aggregates()
        self.assertItemsEqual(aggregate_uuids, re_read_aggregate_uuids)

    def test_set_aggregates_is_replace(self):
        start_aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp = self._create_provider(
            uuidsentinel.rp_name,
            *start_aggregate_uuids,
            uuid=uuidsentinel.rp_uuid
        )

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
        start_aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp = self._create_provider(
            uuidsentinel.rp_name,
            *start_aggregate_uuids,
            uuid=uuidsentinel.rp_uuid
        )
        aggs = rp.get_aggregates()
        self.assertEqual(2, len(aggs))
        rp.destroy()
        aggs = rp.get_aggregates()
        self.assertEqual(0, len(aggs))

    def test_anchors_for_sharing_providers(self):
        """Test _anchors_for_sharing_providers with the following setup.

      .............agg2.....
     :                      :
     :  +====+               : +====+                ..agg5..
     :  | r1 |                .| r2 |               : +----+ :
     :  +=+==+                 +=+==+     +----+    : | s3 | :
     :    |                      |        | s2 |    : +----+ :
     :  +=+==+ agg1            +=+==+     +----+     ........
     :  | c1 |.....            | c2 |       :
     :  +====+ :   :           +====+     agg4        +----+
     :        :     :            :          :         | s4 |
     :    +----+   +----+        :        +====+      +----+
     :....| s5 |   | s1 |.......agg3......| r3 |
     :    +----+   +----+                 +====+
     :.........agg2...:
        """
        agg1 = uuidsentinel.agg1
        agg2 = uuidsentinel.agg2
        agg3 = uuidsentinel.agg3
        agg4 = uuidsentinel.agg4
        agg5 = uuidsentinel.agg5
        shr_trait = rp_obj.Trait.get_by_name(
            self.ctx, "MISC_SHARES_VIA_AGGREGATE")

        def mkrp(name, sharing, aggs, **kwargs):
            rp = self._create_provider(name, *aggs, **kwargs)
            if sharing:
                rp.set_traits(rp_obj.TraitList(objects=[shr_trait]))
            rp.set_aggregates(aggs)
            return rp

        # r1 and c1 constitute a tree.  The child is in agg1.  We use this to
        # show that, when we ask for anchors for s1 (a member of agg1), we get
        # the *root* of the tree, not the aggregate member itself (c1).
        r1 = mkrp('r1', False, [])
        mkrp('c1', False, [agg1], parent=r1.uuid)
        # r2 and c2 constitute a tree.  The root is in agg2; the child is in
        # agg3.  We use this to show that, when we ask for anchors for a
        # provider that's in both of those aggregates (s1), we only get r2 once
        r2 = mkrp('r2', False, [agg2])
        mkrp('c2', False, [agg3], parent=r2.uuid)
        # r3 stands alone, but is a member of two aggregates.  We use this to
        # show that we don't "jump aggregates" - when we ask for anchors for s2
        # we only get r3 (and s2 itself).
        r3 = mkrp('r3', False, [agg3, agg4])
        # s* are sharing providers
        s1 = mkrp('s1', True, [agg1, agg2, agg3])
        s2 = mkrp('s2', True, [agg4])
        # s3 is the only member of agg5.  We use this to show that the provider
        # is still considered its own root, even if the aggregate is only
        # associated with itself.
        s3 = mkrp('s3', True, [agg5])
        # s4 is a broken semi-sharing provider - has MISC_SHARES_VIA_AGGREGATE,
        # but is not a member of an aggregate.  It has no "anchor".
        s4 = mkrp('s4', True, [])
        # s5 is a sharing provider whose aggregates overlap with those of s1.
        # s5 and s1 will show up as "anchors" for each other.
        s5 = mkrp('s5', True, [agg1, agg2])

        # s1 gets s1 (self),
        # r1 via agg1 through c1,
        # r2 via agg2 AND via agg3 through c2
        # r3 via agg3
        # s5 via agg1 and agg2
        expected = set([(s1.uuid, rp.uuid) for rp in (s1, r1, r2, r3, s5)])
        self.assertItemsEqual(
            expected, rp_obj._anchors_for_sharing_providers(self.ctx, [s1.id]))

        # Get same result (id format) when we set get_id=True
        expected = set([(s1.id, rp.id) for rp in (s1, r1, r2, r3, s5)])
        self.assertItemsEqual(
            expected, rp_obj._anchors_for_sharing_providers(self.ctx, [s1.id],
                                                            get_id=True))

        # s2 gets s2 (self) and r3 via agg4
        expected = set([(s2.uuid, rp.uuid) for rp in (s2, r3)])
        self.assertItemsEqual(
            expected, rp_obj._anchors_for_sharing_providers(self.ctx, [s2.id]))

        # s3 gets self
        self.assertEqual(
            set([(s3.uuid, s3.uuid)]), rp_obj._anchors_for_sharing_providers(
                self.ctx, [s3.id]))

        # s4 isn't really a sharing provider - gets nothing
        self.assertEqual(
            set([]), rp_obj._anchors_for_sharing_providers(self.ctx, [s4.id]))

        # s5 gets s5 (self),
        # r1 via agg1 through c1,
        # r2 via agg2
        # s1 via agg1 and agg2
        expected = set([(s5.uuid, rp.uuid) for rp in (s5, r1, r2, s1)])
        self.assertItemsEqual(
            expected, rp_obj._anchors_for_sharing_providers(self.ctx, [s5.id]))

        # validate that we can get them all at once
        expected = set(
            [(s1.id, rp.id) for rp in (r1, r2, r3, s1, s5)] +
            [(s2.id, rp.id) for rp in (r3, s2)] +
            [(s3.id, rp.id) for rp in (s3,)] +
            [(s5.id, rp.id) for rp in (r1, r2, s1, s5)]
        )
        self.assertItemsEqual(
            expected, rp_obj._anchors_for_sharing_providers(self.ctx,
                [s1.id, s2.id, s3.id, s4.id, s5.id], get_id=True))


class TestAllocation(tb.PlacementDbBaseTestCase):

    def test_create_list_and_delete_allocation(self):
        rp, _ = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)

        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, rp)

        self.assertEqual(1, len(allocations))

        self.assertEqual(DISK_ALLOCATION['used'],
                        allocations[0].used)

        allocations.delete_all()

        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, rp)

        self.assertEqual(0, len(allocations))

    def test_delete_all_with_multiple_consumers(self):
        """Tests fix for LP #1781430 where AllocationList.delete_all() when
        issued for an AllocationList returned by
        AllocationList.get_by_resource_provider() where the resource provider
        had multiple consumers allocated against it, left the DB in an
        inconsistent state.
        """
        # Create a single resource provider and allocate resources for two
        # instances from it. Then grab all the provider's allocations with
        # AllocationList.get_all_by_resource_provider() and attempt to delete
        # them all with AllocationList.delete_all(). After which, another call
        # to AllocationList.get_all_by_resource_provider() should return an
        # empty list.
        cn1 = self._create_provider('cn1')
        tb.add_inventory(cn1, 'VCPU', 8)

        c1_uuid = uuidsentinel.consumer1
        c2_uuid = uuidsentinel.consumer2

        for c_uuid in (c1_uuid, c2_uuid):
            self.allocate_from_provider(cn1, 'VCPU', 1, consumer_id=c_uuid)

        allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn1)
        self.assertEqual(2, len(allocs))

        allocs.delete_all()

        allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn1)
        self.assertEqual(0, len(allocs))

    def test_multi_provider_allocation(self):
        """Tests that an allocation that includes more than one resource
        provider can be created, listed and deleted properly.

        Bug #1707669 highlighted a situation that arose when attempting to
        remove part of an allocation for a source host during a resize
        operation where the exiting allocation was not being properly
        deleted.
        """
        cn_source = self._create_provider('cn_source')
        cn_dest = self._create_provider('cn_dest')

        # Add same inventory to both source and destination host
        for cn in (cn_source, cn_dest):
            tb.add_inventory(cn, fields.ResourceClass.VCPU, 24,
                             allocation_ratio=16.0)
            tb.add_inventory(cn, fields.ResourceClass.MEMORY_MB, 1024,
                             min_unit=64,
                             max_unit=1024,
                             step_size=64,
                             allocation_ratio=1.5)

        # Create a consumer representing the instance
        inst_consumer = consumer_obj.Consumer(
            self.ctx, uuid=uuidsentinel.instance, user=self.user_obj,
            project=self.project_obj)
        inst_consumer.create()

        # Now create an allocation that represents a move operation where the
        # scheduler has selected cn_dest as the target host and created a
        # "doubled-up" allocation for the duration of the move operation
        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_source,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_source,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
            ])
        alloc_list.replace_all()

        src_allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn_source)

        self.assertEqual(2, len(src_allocs))

        dest_allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn_dest)

        self.assertEqual(2, len(dest_allocs))

        consumer_allocs = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, uuidsentinel.instance)

        self.assertEqual(4, len(consumer_allocs))

        # Validate that when we create an allocation for a consumer that we
        # delete any existing allocation and replace it with what the new.
        # Here, we're emulating the step that occurs on confirm_resize() where
        # the source host pulls the existing allocation for the instance and
        # removes any resources that refer to itself and saves the allocation
        # back to placement
        new_alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
            ])
        new_alloc_list.replace_all()

        src_allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn_source)

        self.assertEqual(0, len(src_allocs))

        dest_allocs = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, cn_dest)

        self.assertEqual(2, len(dest_allocs))

        consumer_allocs = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, uuidsentinel.instance)

        self.assertEqual(2, len(consumer_allocs))

    def test_get_all_by_resource_provider(self):
        rp, allocation = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)
        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, rp)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp.id, allocations[0].resource_provider.id)
        self.assertEqual(allocation.resource_provider.id,
                         allocations[0].resource_provider.id)


class TestAllocationListCreateDelete(tb.PlacementDbBaseTestCase):

    def test_allocation_checking(self):
        """Test that allocation check logic works with 2 resource classes on
        one provider.

        If this fails, we get a KeyError at replace_all()
        """

        max_unit = 10
        consumer_uuid = uuidsentinel.consumer
        consumer_uuid2 = uuidsentinel.consumer2

        # Create a consumer representing the two instances
        consumer = consumer_obj.Consumer(
            self.ctx, uuid=consumer_uuid, user=self.user_obj,
            project=self.project_obj)
        consumer.create()
        consumer2 = consumer_obj.Consumer(
            self.ctx, uuid=consumer_uuid2, user=self.user_obj,
            project=self.project_obj)
        consumer2.create()

        # Create one resource provider with 2 classes
        rp1_name = uuidsentinel.rp1_name
        rp1_uuid = uuidsentinel.rp1_uuid
        rp1_class = fields.ResourceClass.DISK_GB
        rp1_used = 6

        rp2_class = fields.ResourceClass.IPV4_ADDRESS
        rp2_used = 2

        rp1 = self._create_provider(rp1_name, uuid=rp1_uuid)
        tb.add_inventory(rp1, rp1_class, 1024, max_unit=max_unit)
        tb.add_inventory(rp1, rp2_class, 255, reserved=2, max_unit=max_unit)

        # create the allocations for a first consumer
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer=consumer,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer=consumer,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])
        allocation_list.replace_all()

        # create the allocations for a second consumer, until we have
        # allocations for more than one consumer in the db, then we
        # won't actually be doing real allocation math, which triggers
        # the sql monster.
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer=consumer2,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer=consumer2,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])
        # If we are joining wrong, this will be a KeyError
        allocation_list.replace_all()

    def test_allocation_list_create(self):
        max_unit = 10
        consumer_uuid = uuidsentinel.consumer

        # Create a consumer representing the instance
        inst_consumer = consumer_obj.Consumer(
            self.ctx, uuid=consumer_uuid, user=self.user_obj,
            project=self.project_obj)
        inst_consumer.create()

        # Create two resource providers
        rp1_name = uuidsentinel.rp1_name
        rp1_uuid = uuidsentinel.rp1_uuid
        rp1_class = fields.ResourceClass.DISK_GB
        rp1_used = 6

        rp2_name = uuidsentinel.rp2_name
        rp2_uuid = uuidsentinel.rp2_uuid
        rp2_class = fields.ResourceClass.IPV4_ADDRESS
        rp2_used = 2

        rp1 = self._create_provider(rp1_name, uuid=rp1_uuid)
        rp2 = self._create_provider(rp2_name, uuid=rp2_uuid)

        # Two allocations, one for each resource provider.
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer=inst_consumer,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp2,
                                         consumer=inst_consumer,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])

        # There's no inventory, we have a failure.
        error = self.assertRaises(exception.InvalidInventory,
                                  allocation_list.replace_all)
        # Confirm that the resource class string, not index, is in
        # the exception and resource providers are listed by uuid.
        self.assertIn(rp1_class, str(error))
        self.assertIn(rp2_class, str(error))
        self.assertIn(rp1.uuid, str(error))
        self.assertIn(rp2.uuid, str(error))

        # Add inventory for one of the two resource providers. This should also
        # fail, since rp2 has no inventory.
        tb.add_inventory(rp1, rp1_class, 1024, max_unit=1)
        self.assertRaises(exception.InvalidInventory,
                          allocation_list.replace_all)

        # Add inventory for the second resource provider
        tb.add_inventory(rp2, rp2_class, 255, reserved=2, max_unit=1)

        # Now the allocations will still fail because max_unit 1
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          allocation_list.replace_all)
        inv1 = rp_obj.Inventory(resource_provider=rp1,
                                resource_class=rp1_class,
                                total=1024, max_unit=max_unit)
        inv1.obj_set_defaults()
        rp1.set_inventory(rp_obj.InventoryList(objects=[inv1]))
        inv2 = rp_obj.Inventory(resource_provider=rp2,
                                resource_class=rp2_class,
                                total=255, reserved=2, max_unit=max_unit)
        inv2.obj_set_defaults()
        rp2.set_inventory(rp_obj.InventoryList(objects=[inv2]))

        # Now we can finally allocate.
        allocation_list.replace_all()

        # Check that those allocations changed usage on each
        # resource provider.
        rp1_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp1_uuid)
        rp2_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp2_uuid)
        self.assertEqual(rp1_used, rp1_usage[0].usage)
        self.assertEqual(rp2_used, rp2_usage[0].usage)

        # redo one allocation
        # TODO(cdent): This does not currently behave as expected
        # because a new allocataion is created, adding to the total
        # used, not replacing.
        rp1_used += 1
        self.allocate_from_provider(rp1, rp1_class, rp1_used,
                                  consumer=inst_consumer)

        rp1_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp1_uuid)
        self.assertEqual(rp1_used, rp1_usage[0].usage)

        # delete the allocations for the consumer
        # NOTE(cdent): The database uses 'consumer_id' for the
        # column, presumably because some ids might not be uuids, at
        # some point in the future.
        consumer_allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        consumer_allocations.delete_all()

        rp1_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp1_uuid)
        rp2_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp2_uuid)
        self.assertEqual(0, rp1_usage[0].usage)
        self.assertEqual(0, rp2_usage[0].usage)

    def _make_rp_and_inventory(self, **kwargs):
        # Create one resource provider and set some inventory
        rp_name = kwargs.get('rp_name') or uuidsentinel.rp_name
        rp_uuid = kwargs.get('rp_uuid') or uuidsentinel.rp_uuid
        rp = self._create_provider(rp_name, uuid=rp_uuid)
        rc = kwargs.pop('resource_class')
        tb.add_inventory(rp, rc, 1024, **kwargs)
        return rp

    def _validate_usage(self, rp, usage):
        rp_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp.uuid)
        self.assertEqual(usage, rp_usage[0].usage)

    def _check_create_allocations(self, inventory_kwargs,
                                  bad_used, good_used):
        rp_class = fields.ResourceClass.DISK_GB
        rp = self._make_rp_and_inventory(resource_class=rp_class,
                                         **inventory_kwargs)

        # allocation, bad step_size
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          self.allocate_from_provider, rp, rp_class, bad_used)

        # correct for step size
        self.allocate_from_provider(rp, rp_class, good_used)

        # check usage
        self._validate_usage(rp, good_used)

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

    def test_create_and_clear(self):
        """Test that a used of 0 in an allocation wipes allocations."""
        consumer_uuid = uuidsentinel.consumer

        # Create a consumer representing the instance
        inst_consumer = consumer_obj.Consumer(
            self.ctx, uuid=consumer_uuid, user=self.user_obj,
            project=self.project_obj)
        inst_consumer.create()

        rp_class = fields.ResourceClass.DISK_GB
        target_rp = self._make_rp_and_inventory(resource_class=rp_class,
                                                max_unit=500)

        # Create two allocations with values and confirm the resulting
        # usage is as expected.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer=inst_consumer,
                                        resource_class=rp_class,
                                        used=100)
        allocation2 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer=inst_consumer,
                                        resource_class=rp_class,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.replace_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(2, len(allocations))
        usage = sum(alloc.used for alloc in allocations)
        self.assertEqual(300, usage)

        # Create two allocations, one with 0 used, to confirm the
        # resulting usage is only of one.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                         consumer=inst_consumer,
                                         resource_class=rp_class,
                                         used=0)
        allocation2 = rp_obj.Allocation(resource_provider=target_rp,
                                         consumer=inst_consumer,
                                         resource_class=rp_class,
                                         used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.replace_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        # add a source rp and a migration consumer
        migration_uuid = uuidsentinel.migration

        # Create a consumer representing the migration
        mig_consumer = consumer_obj.Consumer(
            self.ctx, uuid=migration_uuid, user=self.user_obj,
            project=self.project_obj)
        mig_consumer.create()

        source_rp = self._make_rp_and_inventory(
            rp_name=uuidsentinel.source_name, rp_uuid=uuidsentinel.source_uuid,
            resource_class=rp_class, max_unit=500)

        # Create two allocations, one as the consumer, one as the
        # migration.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer=inst_consumer,
                                        resource_class=rp_class,
                                        used=200)
        allocation2 = rp_obj.Allocation(resource_provider=source_rp,
                                        consumer=mig_consumer,
                                        resource_class=rp_class,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.replace_all()

        # Check primary consumer allocations.
        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        # Check migration allocations.
        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, migration_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        # Clear the migration and confirm the target.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer=inst_consumer,
                                        resource_class=rp_class,
                                        used=200)
        allocation2 = rp_obj.Allocation(resource_provider=source_rp,
                                        consumer=mig_consumer,
                                        resource_class=rp_class,
                                        used=0)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.replace_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, migration_uuid)
        self.assertEqual(0, len(allocations))

    def test_create_exceeding_capacity_allocation(self):
        """Tests on a list of allocations which contains an invalid allocation
        exceeds resource provider's capacity.

        Expect InvalidAllocationCapacityExceeded to be raised and all
        allocations in the list should not be applied.

        """
        empty_rp = self._create_provider('empty_rp')
        full_rp = self._create_provider('full_rp')

        for rp in (empty_rp, full_rp):
            tb.add_inventory(rp, fields.ResourceClass.VCPU, 24,
                             allocation_ratio=16.0)
            tb.add_inventory(rp, fields.ResourceClass.MEMORY_MB, 1024,
                             min_unit=64,
                             max_unit=1024,
                             step_size=64)

        # Create a consumer representing the instance
        inst_consumer = consumer_obj.Consumer(
            self.ctx, uuid=uuidsentinel.instance, user=self.user_obj,
            project=self.project_obj)
        inst_consumer.create()

        # First create a allocation to consume full_rp's resource.
        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=full_rp,
                    resource_class=fields.ResourceClass.VCPU,
                    used=12),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=full_rp,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=1024)
            ])
        alloc_list.replace_all()

        # Create a consumer representing the second instance
        inst2_consumer = consumer_obj.Consumer(
            self.ctx, uuid=uuidsentinel.instance2, user=self.user_obj,
            project=self.project_obj)
        inst2_consumer.create()

        # Create an allocation list consisting of valid requests and an invalid
        # request exceeding the memory full_rp can provide.
        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst2_consumer,
                    resource_provider=empty_rp,
                    resource_class=fields.ResourceClass.VCPU,
                    used=12),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst2_consumer,
                    resource_provider=empty_rp,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=512),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst2_consumer,
                    resource_provider=full_rp,
                    resource_class=fields.ResourceClass.VCPU,
                    used=12),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst2_consumer,
                    resource_provider=full_rp,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=512),
            ])

        self.assertRaises(exception.InvalidAllocationCapacityExceeded,
                          alloc_list.replace_all)

        # Make sure that allocations of both empty_rp and full_rp remain
        # unchanged.
        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, full_rp)
        self.assertEqual(2, len(allocations))

        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, empty_rp)
        self.assertEqual(0, len(allocations))

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.LOG')
    def test_set_allocations_retry(self, mock_log):
        """Test server side allocation write retry handling."""

        # Create a single resource provider and give it some inventory.
        rp1 = self._create_provider('rp1')
        tb.add_inventory(rp1, fields.ResourceClass.VCPU, 24,
                         allocation_ratio=16.0)
        tb.add_inventory(rp1, fields.ResourceClass.MEMORY_MB, 1024,
                         min_unit=64,
                         max_unit=1024,
                         step_size=64)
        original_generation = rp1.generation
        # Verify the generation is what we expect (we'll be checking again
        # later).
        self.assertEqual(2, original_generation)

        # Create a consumer and have it make an allocation.
        inst_consumer = consumer_obj.Consumer(
            self.ctx, uuid=uuidsentinel.instance, user=self.user_obj,
            project=self.project_obj)
        inst_consumer.create()

        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=rp1,
                    resource_class=fields.ResourceClass.VCPU,
                    used=12),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer=inst_consumer,
                    resource_provider=rp1,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=1024)
            ])

        # Make sure the right exception happens when the retry loop expires.
        with mock.patch.object(rp_obj.AllocationList,
                               'RP_CONFLICT_RETRY_COUNT', 0):
            self.assertRaises(
                exception.ResourceProviderConcurrentUpdateDetected,
                alloc_list.replace_all)
            mock_log.warning.assert_called_with(
                'Exceeded retry limit of %d on allocations write', 0)

        # Make sure the right thing happens after a small number of failures.
        # There's a bit of mock magic going on here to enusre that we can
        # both do some side effects on _set_allocations as well as have the
        # real behavior. Two generation conflicts and then a success.
        mock_log.reset_mock()
        with mock.patch.object(rp_obj.AllocationList,
                               'RP_CONFLICT_RETRY_COUNT', 3):
            unmocked_set = functools.partial(
                rp_obj.AllocationList._set_allocations, alloc_list)
            with mock.patch(
                'nova.api.openstack.placement.objects.resource_provider.'
                'AllocationList._set_allocations') as mock_set:
                exceptions = iter([
                    exception.ResourceProviderConcurrentUpdateDetected(),
                    exception.ResourceProviderConcurrentUpdateDetected(),
                ])

                def side_effect(*args, **kwargs):
                    try:
                        raise next(exceptions)
                    except StopIteration:
                        return unmocked_set(*args, **kwargs)

                mock_set.side_effect = side_effect
                alloc_list.replace_all()
                self.assertEqual(2, mock_log.debug.call_count)
                mock_log.debug.called_with(
                    'Retrying allocations write on resource provider '
                    'generation conflict')
                self.assertEqual(3, mock_set.call_count)

        # Confirm we're using a different rp object after the change
        # and that it has a higher generation.
        new_rp = alloc_list[0].resource_provider
        self.assertEqual(original_generation, rp1.generation)
        self.assertEqual(original_generation + 1, new_rp.generation)


class UsageListTestCase(tb.PlacementDbBaseTestCase):

    def test_get_all_null(self):
        for uuid in [uuidsentinel.rp_uuid_1, uuidsentinel.rp_uuid_2]:
            self._create_provider(uuid, uuid=uuid)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, uuidsentinel.rp_uuid_1)
        self.assertEqual(0, len(usage_list))

    def test_get_all_one_allocation(self):
        db_rp, _ = self._make_allocation(DISK_INVENTORY, DISK_ALLOCATION)
        inv = rp_obj.Inventory(resource_provider=db_rp,
                               resource_class=fields.ResourceClass.DISK_GB,
                               total=1024)
        inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv])
        db_rp.set_inventory(inv_list)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, db_rp.uuid)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(2, usage_list[0].usage)
        self.assertEqual(fields.ResourceClass.DISK_GB,
                         usage_list[0].resource_class)

    def test_get_inventory_no_allocation(self):
        db_rp = self._create_provider('rp_no_inv')
        tb.add_inventory(db_rp, fields.ResourceClass.DISK_GB, 1024)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, db_rp.uuid)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(0, usage_list[0].usage)
        self.assertEqual(fields.ResourceClass.DISK_GB,
                         usage_list[0].resource_class)

    def test_get_all_multiple_inv(self):
        db_rp = self._create_provider('rp_no_inv')
        tb.add_inventory(db_rp, fields.ResourceClass.DISK_GB, 1024)
        tb.add_inventory(db_rp, fields.ResourceClass.VCPU, 24)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, db_rp.uuid)
        self.assertEqual(2, len(usage_list))


class ResourceClassListTestCase(tb.PlacementDbBaseTestCase):

    def test_get_all_no_custom(self):
        """Test that if we haven't yet added any custom resource classes, that
        we only get a list of ResourceClass objects representing the standard
        classes.
        """
        rcs = rp_obj.ResourceClassList.get_all(self.ctx)
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
        with self.placement_db.get_engine().connect() as conn:
            for custom in customs:
                c_name, c_id = custom
                ins = rp_obj._RC_TBL.insert().values(id=c_id, name=c_name)
                conn.execute(ins)

        rcs = rp_obj.ResourceClassList.get_all(self.ctx)
        expected_count = len(fields.ResourceClass.STANDARD) + len(customs)
        self.assertEqual(expected_count, len(rcs))


class ResourceClassTestCase(tb.PlacementDbBaseTestCase):

    def test_get_by_name(self):
        rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            fields.ResourceClass.VCPU
        )
        vcpu_id = fields.ResourceClass.STANDARD.index(
            fields.ResourceClass.VCPU
        )
        self.assertEqual(vcpu_id, rc.id)
        self.assertEqual(fields.ResourceClass.VCPU, rc.name)

    def test_get_by_name_not_found(self):
        self.assertRaises(exception.ResourceClassNotFound,
                          rp_obj.ResourceClass.get_by_name,
                          self.ctx,
                          'CUSTOM_NO_EXISTS')

    def test_get_by_name_custom(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        get_rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            'CUSTOM_IRON_NFV',
        )
        self.assertEqual(rc.id, get_rc.id)
        self.assertEqual(rc.name, get_rc.name)

    def test_create_fail_not_using_namespace(self):
        rc = rp_obj.ResourceClass(
            context=self.ctx,
            name='IRON_NFV',
        )
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('name must start with', str(exc))

    def test_create_duplicate_standard(self):
        rc = rp_obj.ResourceClass(
            context=self.ctx,
            name=fields.ResourceClass.VCPU,
        )
        self.assertRaises(exception.ResourceClassExists, rc.create)

    def test_create(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        min_id = rp_obj.ResourceClass.MIN_CUSTOM_RESOURCE_CLASS_ID
        self.assertEqual(min_id, rc.id)

        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_ENTERPRISE',
        )
        rc.create()
        self.assertEqual(min_id + 1, rc.id)

    @mock.patch.object(
        nova.api.openstack.placement.objects.resource_provider.ResourceClass,
        "_get_next_id")
    def test_create_duplicate_id_retry(self, mock_get):
        # This order of ID generation will create rc1 with an ID of 42, try to
        # create rc2 with the same ID, and then return 43 in the retry loop.
        mock_get.side_effect = (42, 42, 43)
        rc1 = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc1.create()
        rc2 = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_TWO',
        )
        rc2.create()
        self.assertEqual(rc1.id, 42)
        self.assertEqual(rc2.id, 43)

    @mock.patch.object(
        nova.api.openstack.placement.objects.resource_provider.ResourceClass,
        "_get_next_id")
    def test_create_duplicate_id_retry_failing(self, mock_get):
        """negative case for test_create_duplicate_id_retry"""
        # This order of ID generation will create rc1 with an ID of 44, try to
        # create rc2 with the same ID, and then return 45 in the retry loop.
        mock_get.side_effect = (44, 44, 44, 44)
        rc1 = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc1.create()
        rc2 = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_TWO',
        )
        rc2.RESOURCE_CREATE_RETRY_COUNT = 3
        self.assertRaises(exception.MaxDBRetriesExceeded, rc2.create)

    def test_create_duplicate_custom(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        self.assertEqual(rp_obj.ResourceClass.MIN_CUSTOM_RESOURCE_CLASS_ID,
                         rc.id)
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ResourceClassExists, rc.create)

    def test_destroy_fail_no_id(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ObjectActionError, rc.destroy)

    def test_destroy_fail_standard(self):
        rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            'VCPU',
        )
        self.assertRaises(exception.ResourceClassCannotDeleteStandard,
                          rc.destroy)

    def test_destroy(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        rc_list = rp_obj.ResourceClassList.get_all(self.ctx)
        rc_ids = (r.id for r in rc_list)
        self.assertIn(rc.id, rc_ids)

        rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            'CUSTOM_IRON_NFV',
        )

        rc.destroy()
        rc_list = rp_obj.ResourceClassList.get_all(self.ctx)
        rc_ids = (r.id for r in rc_list)
        self.assertNotIn(rc.id, rc_ids)

        # Verify rc cache was purged of the old entry
        self.assertRaises(exception.ResourceClassNotFound,
                          rp_obj.ResourceClass.get_by_name,
                          self.ctx,
                          'CUSTOM_IRON_NFV')

    def test_destroy_fail_with_inventory(self):
        """Test that we raise an exception when attempting to delete a resource
        class that is referenced in an inventory record.
        """
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()
        rp = rp_obj.ResourceProvider(
            self.ctx,
            name='my rp',
            uuid=uuidsentinel.rp,
        )
        rp.create()
        inv = rp_obj.Inventory(
            resource_provider=rp,
            resource_class='CUSTOM_IRON_NFV',
            total=1,
        )
        inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv])
        rp.set_inventory(inv_list)

        self.assertRaises(exception.ResourceClassInUse,
                          rc.destroy)

        rp.set_inventory(rp_obj.InventoryList(objects=[]))
        rc.destroy()
        rc_list = rp_obj.ResourceClassList.get_all(self.ctx)
        rc_ids = (r.id for r in rc_list)
        self.assertNotIn(rc.id, rc_ids)

    def test_save_fail_no_id(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        self.assertRaises(exception.ObjectActionError, rc.save)

    def test_save_fail_standard(self):
        rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            'VCPU',
        )
        self.assertRaises(exception.ResourceClassCannotUpdateStandard,
                          rc.save)

    def test_save(self):
        rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_IRON_NFV',
        )
        rc.create()

        rc = rp_obj.ResourceClass.get_by_name(
            self.ctx,
            'CUSTOM_IRON_NFV',
        )
        rc.name = 'CUSTOM_IRON_SILVER'
        rc.save()

        # Verify rc cache was purged of the old entry
        self.assertRaises(exception.NotFound,
                          rp_obj.ResourceClass.get_by_name,
                          self.ctx,
                          'CUSTOM_IRON_NFV')


class ResourceProviderTraitTestCase(tb.PlacementDbBaseTestCase):

    def _assert_traits(self, expected_traits, traits_objs):
        expected_traits.sort()
        traits = []
        for obj in traits_objs:
            traits.append(obj.name)
        traits.sort()
        self.assertEqual(expected_traits, traits)

    def _assert_traits_in(self, expected_traits, traits_objs):
        traits = [trait.name for trait in traits_objs]
        for expected in expected_traits:
            self.assertIn(expected, traits)

    def test_trait_create(self):
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        self.assertIn('id', t)
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')

    def test_trait_create_with_id_set(self):
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.id = 1
        self.assertRaises(exception.ObjectActionError, t.create)

    def test_trait_create_without_name_set(self):
        t = rp_obj.Trait(self.ctx)
        self.assertRaises(exception.ObjectActionError, t.create)

    def test_trait_create_duplicated_trait(self):
        trait = rp_obj.Trait(self.ctx)
        trait.name = 'CUSTOM_TRAIT_A'
        trait.create()
        tmp_trait = rp_obj.Trait.get_by_name(self.ctx, 'CUSTOM_TRAIT_A')
        self.assertEqual('CUSTOM_TRAIT_A', tmp_trait.name)
        duplicated_trait = rp_obj.Trait(self.ctx)
        duplicated_trait.name = 'CUSTOM_TRAIT_A'
        self.assertRaises(exception.TraitExists, duplicated_trait.create)

    def test_trait_get(self):
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        t = rp_obj.Trait.get_by_name(self.ctx, 'CUSTOM_TRAIT_A')
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')

    def test_trait_get_non_existed_trait(self):
        self.assertRaises(exception.TraitNotFound,
            rp_obj.Trait.get_by_name, self.ctx, 'CUSTOM_TRAIT_A')

    def test_bug_1760322(self):
        # Under bug # #1760322, if the first hit to the traits table resulted
        # in an exception, the sync transaction rolled back and the table
        # stayed empty; but _TRAITS_SYNCED got set to True, so it didn't resync
        # next time.
        # NOTE(cdent): With change Ic87518948ed5bf4ab79f9819cd94714e350ce265
        # syncing is no longer done in the same way, so the bug fix that this
        # test was testing is gone, but this test has been left in place to
        # make sure we still get behavior we expect.
        try:
            rp_obj.Trait.get_by_name(self.ctx, 'CUSTOM_GOLD')
        except exception.TraitNotFound:
            pass
        # Under bug #1760322, this raised TraitNotFound.
        rp_obj.Trait.get_by_name(self.ctx, os_traits.HW_CPU_X86_AVX2)

    def test_trait_destroy(self):
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        t = rp_obj.Trait.get_by_name(self.ctx, 'CUSTOM_TRAIT_A')
        self.assertEqual(t.name, 'CUSTOM_TRAIT_A')
        t.destroy()
        self.assertRaises(exception.TraitNotFound, rp_obj.Trait.get_by_name,
                          self.ctx, 'CUSTOM_TRAIT_A')

    def test_trait_destroy_with_standard_trait(self):
        t = rp_obj.Trait(self.ctx)
        t.id = 1
        t.name = 'HW_CPU_X86_AVX'
        self.assertRaises(exception.TraitCannotDeleteStandard, t.destroy)

    def test_traits_get_all(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()

        self._assert_traits_in(trait_names,
                               rp_obj.TraitList.get_all(self.ctx))

    def test_traits_get_all_with_name_in_filter(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()

        traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        self._assert_traits(['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B'], traits)

    def test_traits_get_all_with_non_existed_name(self):
        traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': ['CUSTOM_TRAIT_X', 'CUSTOM_TRAIT_Y']})
        self.assertEqual(0, len(traits))

    def test_traits_get_all_with_prefix_filter(self):
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()

        traits = rp_obj.TraitList.get_all(self.ctx,
                                           filters={'prefix': 'CUSTOM'})
        self._assert_traits(
            ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C'],
            traits)

    def test_traits_get_all_with_non_existed_prefix(self):
        traits = rp_obj.TraitList.get_all(self.ctx,
            filters={"prefix": "NOT_EXISTED"})
        self.assertEqual(0, len(traits))

    def test_set_traits_for_resource_provider(self):
        rp = self._create_provider('fake_resource_provider')
        generation = rp.generation
        self.assertIsInstance(rp.id, int)

        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        tb.set_traits(rp, *trait_names)

        rp_traits = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self._assert_traits(trait_names, rp_traits)
        self.assertEqual(rp.generation, generation + 1)
        generation = rp.generation

        trait_names.remove('CUSTOM_TRAIT_A')
        updated_traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': trait_names})
        self._assert_traits(trait_names, updated_traits)
        tb.set_traits(rp, *trait_names)
        rp_traits = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self._assert_traits(trait_names, rp_traits)
        self.assertEqual(rp.generation, generation + 1)

    def test_set_traits_for_correct_resource_provider(self):
        """This test creates two ResourceProviders, and attaches same trait to
        both of them. Then detaching the trait from one of them, and ensure
        the trait still associated with another one.
        """
        # Create two ResourceProviders
        rp1 = self._create_provider('fake_resource_provider1')
        rp2 = self._create_provider('fake_resource_provider2')

        tname = 'CUSTOM_TRAIT_A'

        # Associate the trait with two ResourceProviders
        tb.set_traits(rp1, tname)
        tb.set_traits(rp2, tname)

        # Ensure the association
        rp1_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp1)
        rp2_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp2)
        self._assert_traits([tname], rp1_traits)
        self._assert_traits([tname], rp2_traits)

        # Detach the trait from one of ResourceProvider, and ensure the
        # trait association with another ResourceProvider still exists.
        tb.set_traits(rp1)
        rp1_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp1)
        rp2_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp2)
        self._assert_traits([], rp1_traits)
        self._assert_traits([tname], rp2_traits)

    def test_trait_delete_in_use(self):
        rp = self._create_provider('fake_resource_provider')
        t, = tb.set_traits(rp, 'CUSTOM_TRAIT_A')
        self.assertRaises(exception.TraitInUse, t.destroy)

    def test_traits_get_all_with_associated_true(self):
        rp1 = self._create_provider('fake_resource_provider1')
        rp2 = self._create_provider('fake_resource_provider2')
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()

        associated_traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        rp1.set_traits(associated_traits)
        rp2.set_traits(associated_traits)
        self._assert_traits(['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B'],
            rp_obj.TraitList.get_all(self.ctx,
                filters={'associated': True}))

    def test_traits_get_all_with_associated_false(self):
        rp1 = self._create_provider('fake_resource_provider1')
        rp2 = self._create_provider('fake_resource_provider2')
        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()

        associated_traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B']})
        rp1.set_traits(associated_traits)
        rp2.set_traits(associated_traits)
        self._assert_traits_in(['CUSTOM_TRAIT_C'],
            rp_obj.TraitList.get_all(self.ctx,
                filters={'associated': False}))


class SharedProviderTestCase(tb.PlacementDbBaseTestCase):
    """Tests that the queries used to determine placement in deployments with
    shared resource providers such as a shared disk pool result in accurate
    reporting of inventory and usage.
    """

    def _requested_resources(self):
        STANDARDS = fields.ResourceClass.STANDARD
        VCPU_ID = STANDARDS.index(fields.ResourceClass.VCPU)
        MEMORY_MB_ID = STANDARDS.index(fields.ResourceClass.MEMORY_MB)
        DISK_GB_ID = STANDARDS.index(fields.ResourceClass.DISK_GB)
        # The resources we will request
        resources = {
            VCPU_ID: 1,
            MEMORY_MB_ID: 64,
            DISK_GB_ID: 100,
        }
        return resources

    def test_shared_provider_capacity(self):
        """Sets up a resource provider that shares DISK_GB inventory via an
        aggregate, a couple resource providers representing "local disk"
        compute nodes and ensures the _get_providers_sharing_capacity()
        function finds that provider and not providers of "local disk".
        """
        # Create the two "local disk" compute node providers
        cn1 = self._create_provider('cn1')
        cn2 = self._create_provider('cn2')

        # Populate the two compute node providers with inventory.  One has
        # DISK_GB.  Both should be excluded from the result (one doesn't have
        # the requested resource; but neither is a sharing provider).
        for cn in (cn1, cn2):
            tb.add_inventory(cn, fields.ResourceClass.VCPU, 24,
                             allocation_ratio=16.0)
            tb.add_inventory(cn, fields.ResourceClass.MEMORY_MB, 32768,
                             min_unit=64,
                             max_unit=32768,
                             step_size=64,
                             allocation_ratio=1.5)
            if cn is cn1:
                tb.add_inventory(cn, fields.ResourceClass.DISK_GB, 2000,
                                 min_unit=10,
                                 max_unit=100,
                                 step_size=10)

        # Create the shared storage pool
        ss = self._create_provider('shared storage')

        # Give the shared storage pool some inventory of DISK_GB
        tb.add_inventory(ss, fields.ResourceClass.DISK_GB, 2000,
                         min_unit=10,
                         max_unit=100,
                         step_size=10)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        tb.set_traits(ss, "MISC_SHARES_VIA_AGGREGATE")

        # OK, now that has all been set up, let's verify that we get the ID of
        # the shared storage pool when we ask for DISK_GB
        got_ids = rp_obj._get_providers_with_shared_capacity(
            self.ctx,
            fields.ResourceClass.STANDARD.index(fields.ResourceClass.DISK_GB),
            100,
        )
        self.assertEqual([ss.id], got_ids)
