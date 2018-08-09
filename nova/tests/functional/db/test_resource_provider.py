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
from nova import context
from nova import exception
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


def add_inventory(rp, rc, total, **kwargs):
    kwargs.setdefault('max_unit', total)
    inv = rp_obj.Inventory(rp._context, resource_provider=rp,
                           resource_class=rc, total=total, **kwargs)
    inv.obj_set_defaults()
    rp.add_inventory(inv)
    return inv


class ResourceProviderBaseCase(test.NoDBTestCase):

    USES_DB_SELF = True

    def setUp(self):
        super(ResourceProviderBaseCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.api_db = self.useFixture(fixtures.Database(database='api'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')

    def _make_allocation(self, rp_uuid=None, inv_dict=None):
        rp_uuid = rp_uuid or uuidsentinel.allocation_resource_provider
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=rp_uuid,
            name=rp_uuid)
        rp.create()
        inv_dict = inv_dict or DISK_INVENTORY
        disk_inv = rp_obj.Inventory(context=self.ctx,
                resource_provider=rp, **inv_dict)
        inv_list = rp_obj.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)
        alloc = rp_obj.Allocation(self.ctx, resource_provider=rp,
                **DISK_ALLOCATION)
        alloc_list = rp_obj.AllocationList(self.ctx, objects=[alloc])
        alloc_list.create_all()
        return rp, alloc


class ResourceProviderTestCase(ResourceProviderBaseCase):
    """Test resource-provider objects' lifecycles."""

    def test_provider_traits_empty_param(self):
        self.assertRaises(ValueError, rp_obj._provider_traits,
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
        created_resource_provider = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
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

    def test_root_provider_population(self):
        """Simulate an old resource provider record in the database that has no
        root_provider_uuid set and ensure that when grabbing the resource
        provider object, the root_provider_uuid field in the table is set to
        the provider's UUID.
        """
        rp_tbl = rp_obj._RP_TBL
        conn = self.api_db.get_engine().connect()

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
        rp1 = rp_obj.ResourceProvider(
            context=self.ctx,
            name='rp1',
            uuid=uuidsentinel.rp1,
        )
        rp1.create()

        # Test the root was auto-set to the create provider's UUID
        self.assertEqual(uuidsentinel.rp1, rp1.root_provider_uuid)

        # Create a new provider that we will make the parent of rp1
        parent_rp = rp_obj.ResourceProvider(
            context=self.ctx,
            name='parent',
            uuid=uuidsentinel.parent,
        )
        parent_rp.create()
        self.assertEqual(uuidsentinel.parent, parent_rp.root_provider_uuid)

        # Now change rp1 to be a child of parent and check rp1's root is
        # changed to that of the parent.
        rp1.parent_provider_uuid = parent_rp.uuid
        rp1.save()

        self.assertEqual(uuidsentinel.parent, rp1.root_provider_uuid)

    def test_save_root_provider_failed(self):
        """Test that if we provide a root_provider_uuid value we get an
        ObjectActionError if we save the object.
        """
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            name='rp1',
            uuid=uuidsentinel.rp1,
        )
        rp.create()
        rp.root_provider_uuid = uuidsentinel.noexists
        self.assertRaises(exception.ObjectActionError, rp.save)

    def test_save_unknown_parent_provider(self):
        """Test that if we provide a parent_provider_uuid value that points to
        a resource provider that doesn't exist, that we get an
        ObjectActionError if we save the object.
        """
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            name='rp1',
            uuid=uuidsentinel.rp1,
        )
        rp.create()
        rp.parent_provider_uuid = uuidsentinel.noexists
        self.assertRaises(exception.ObjectActionError, rp.save)

    def test_save_resource_provider(self):
        created_resource_provider = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
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
        cn1 = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.cn1, name='cn1')
        cn1.create()

        cn2 = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.cn2, name='cn2')
        cn2.create()

        cn3 = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.cn3, name='cn3')
        cn3.create()

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
        root_rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.root_rp,
            name='root-rp',
        )
        root_rp.create()

        child_rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.child_rp,
            name='child-rp',
            parent_provider_uuid=uuidsentinel.root_rp,
        )
        child_rp.create()

        grandchild_rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.grandchild_rp,
            name='grandchild-rp',
            parent_provider_uuid=uuidsentinel.child_rp,
        )
        grandchild_rp.create()

        # Verify that the root_provider_uuid of both the child and the
        # grandchild is the UUID of the grandparent
        self.assertEqual(root_rp.uuid, child_rp.root_provider_uuid)
        self.assertEqual(root_rp.uuid, grandchild_rp.root_provider_uuid)

        # Create some inventory in the grandchild, allocate some consumers to
        # the grandchild and then attempt to delete the root provider and child
        # provider, both of which should fail.
        invs = [
            rp_obj.Inventory(
                resource_provider=grandchild_rp,
                resource_class=fields.ResourceClass.VCPU,
                total=1,
                reserved=0,
                allocation_ratio=1.0,
                min_unit=1,
                max_unit=1,
                step_size=1,
            ),
        ]
        inv_list = rp_obj.InventoryList(
            resource_provider=grandchild_rp,
            objects=invs
        )
        grandchild_rp.set_inventory(inv_list)

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
                'member_of': [uuidsentinel.agg],
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
                'member_of': [uuidsentinel.agg],
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

        allocs = [
            rp_obj.Allocation(
                resource_provider=grandchild_rp,
                resource_class=fields.ResourceClass.VCPU,
                consumer_id=uuidsentinel.consumer,
                used=1,
            ),
        ]
        alloc_list = rp_obj.AllocationList(self.ctx, objects=allocs)
        alloc_list.create_all()

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
        conn = self.api_db.get_engine().connect()

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
        with mock.patch('nova.objects.resource_provider.'
                        '_set_root_provider_id'):
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
        cn = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.cn, name='cn')
        cn.create()

        # No parents yet. Should still be False.
        self.assertFalse(rp_obj._has_provider_trees(self.ctx))

        numa0 = rp_obj.ResourceProvider(
            context=self.ctx, uuid=uuidsentinel.numa0, name='numa0',
            parent_provider_uuid=uuidsentinel.cn)
        numa0.create()

        # OK, now we've got a parent, so should be True
        self.assertTrue(rp_obj._has_provider_trees(self.ctx))

    def test_destroy_resource_provider(self):
        created_resource_provider = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        created_resource_provider.create()
        created_resource_provider.destroy()
        self.assertRaises(exception.NotFound,
                          rp_obj.ResourceProvider.get_by_uuid,
                          self.ctx,
                          uuidsentinel.fake_resource_provider)
        self.assertRaises(exception.NotFound,
                          created_resource_provider.destroy)

    def test_destroy_allocated_resource_provider_fails(self):
        rp, allocation = self._make_allocation()
        self.assertRaises(exception.ResourceProviderInUse,
                          rp.destroy)

    def test_destroy_resource_provider_destroy_inventory(self):
        resource_provider = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        resource_provider.create()
        disk_inventory = rp_obj.Inventory(
            context=self.ctx,
            resource_provider=resource_provider,
            **DISK_INVENTORY
        )
        inv_list = rp_obj.InventoryList(context=self.ctx,
                                        objects=[disk_inventory])
        resource_provider.set_inventory(inv_list)
        inventories = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, resource_provider)
        self.assertEqual(1, len(inventories))
        resource_provider.destroy()
        inventories = rp_obj.InventoryList.get_all_by_resource_provider(
            self.ctx, resource_provider)
        self.assertEqual(0, len(inventories))

    def test_set_inventory_unknown_resource_class(self):
        """Test attempting to set inventory to an unknown resource class raises
        an exception.
        """
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.rp_uuid,
            name='compute-host',
        )
        rp.create()

        inv = rp_obj.Inventory(
            resource_provider=rp,
            resource_class='UNKNOWN',
            total=1024,
            reserved=15,
            min_unit=10,
            max_unit=100,
            step_size=10,
            allocation_ratio=1.0,
        )

        inv_list = rp_obj.InventoryList(objects=[inv])
        self.assertRaises(exception.ResourceClassNotFound,
                          rp.set_inventory, inv_list)

    def test_set_inventory_fail_in_used(self):
        """Test attempting to set inventory which would result in removing an
        inventory record for a resource class that still has allocations
        against it.
        """
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.rp_uuid,
            name='compute-host',
        )
        rp.create()

        inv = rp_obj.Inventory(
            resource_provider=rp,
            resource_class='VCPU',
            total=12,
            reserved=0,
            min_unit=1,
            max_unit=12,
            step_size=1,
            allocation_ratio=1.0,
        )

        inv_list = rp_obj.InventoryList(objects=[inv])
        rp.set_inventory(inv_list)

        alloc = rp_obj.Allocation(
            resource_provider=rp,
            resource_class='VCPU',
            consumer_id=uuidsentinel.consumer,
            used=1,
        )

        alloc_list = rp_obj.AllocationList(
            self.ctx,
            objects=[alloc]
        )
        alloc_list.create_all()

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

    @mock.patch('nova.objects.resource_provider.LOG')
    def test_set_inventory_over_capacity(self, mock_log):
        rp = rp_obj.ResourceProvider(context=self.ctx,
                                     uuid=uuidsentinel.rp_uuid,
                                     name=uuidsentinel.rp_name)
        rp.create()

        disk_inv = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=2048,
                reserved=15,
                min_unit=10,
                max_unit=600,
                step_size=10,
                allocation_ratio=1.0)
        vcpu_inv = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                total=12,
                reserved=0,
                min_unit=1,
                max_unit=12,
                step_size=1,
                allocation_ratio=16.0)

        inv_list = rp_obj.InventoryList(objects=[disk_inv, vcpu_inv])
        rp.set_inventory(inv_list)
        self.assertFalse(mock_log.warning.called)

        # Allocate something reasonable for the above inventory
        alloc = rp_obj.Allocation(
            context=self.ctx,
            resource_provider=rp,
            consumer_id=uuidsentinel.consumer,
            resource_class='DISK_GB',
            used=500)
        alloc_list = rp_obj.AllocationList(self.ctx, objects=[alloc])
        alloc_list.create_all()

        # Update our inventory to over-subscribe us after the above allocation
        disk_inv.total = 400
        rp.set_inventory(inv_list)

        # We should succeed, but have logged a warning for going over on disk
        mock_log.warning.assert_called_once_with(
            mock.ANY, {'uuid': rp.uuid, 'resource': 'DISK_GB'})

    def test_provider_modify_inventory(self):
        rp = rp_obj.ResourceProvider(context=self.ctx,
                                     uuid=uuidsentinel.rp_uuid,
                                     name=uuidsentinel.rp_name)
        rp.create()
        saved_generation = rp.generation

        disk_inv = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=1024,
                reserved=15,
                min_unit=10,
                max_unit=100,
                step_size=10,
                allocation_ratio=1.0)

        vcpu_inv = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                total=12,
                reserved=0,
                min_unit=1,
                max_unit=12,
                step_size=1,
                allocation_ratio=16.0)

        # set to new list
        inv_list = rp_obj.InventoryList(objects=[disk_inv, vcpu_inv])
        rp.set_inventory(inv_list)

        # generation has bumped
        self.assertEqual(saved_generation + 1, rp.generation)
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

        # fail when inventory bad
        disk_inv = rp_obj.Inventory(
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
        rp = rp_obj.ResourceProvider(context=self.ctx,
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
        rp = rp_obj.ResourceProvider(context=self.ctx,
                                     uuid=uuidsentinel.rp_uuid,
                                     name=uuidsentinel.rp_name)
        rp.create()
        disk_inv = rp_obj.Inventory(resource_provider=rp,
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

    def test_add_invalid_inventory(self):
        rp = rp_obj.ResourceProvider(context=self.ctx,
                                     uuid=uuidsentinel.rp_uuid,
                                     name=uuidsentinel.rp_name)
        rp.create()
        disk_inv = rp_obj.Inventory(
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
        rp = rp_obj.ResourceProvider(context=self.ctx,
                uuid=uuidsentinel.inventory_resource_provider, name='foo')
        rp.create()
        inv = rp_obj.Inventory(context=self.ctx, resource_provider=rp,
                **DISK_INVENTORY)
        inv_list = rp_obj.InventoryList(context=self.ctx, objects=[inv])
        rp.set_inventory(inv_list)
        expected_gen = rp.generation + 1
        alloc = rp_obj.Allocation(context=self.ctx, resource_provider=rp,
                **DISK_ALLOCATION)
        alloc_list = rp_obj.AllocationList(self.ctx, objects=[alloc])
        alloc_list.create_all()
        self.assertEqual(expected_gen, rp.generation)

    def test_get_all_by_resource_provider_multiple_providers(self):
        rp1 = rp_obj.ResourceProvider(context=self.ctx,
                uuid=uuidsentinel.cn1, name='cn1')
        rp1.create()
        rp2 = rp_obj.ResourceProvider(context=self.ctx,
                uuid=uuidsentinel.cn2, name='cn2')
        rp2.create()

        for rp in (rp1, rp2):
            disk_inv = rp_obj.Inventory(context=self.ctx, resource_provider=rp,
                **DISK_INVENTORY)
            ip_inv = rp_obj.Inventory(context=self.ctx, resource_provider=rp,
                total=10,
                reserved=0,
                min_unit=1,
                max_unit=2,
                step_size=1,
                allocation_ratio=1.0,
                resource_class=fields.ResourceClass.IPV4_ADDRESS)
            inv_list = rp_obj.InventoryList(context=self.ctx,
                objects=[disk_inv, ip_inv])
            rp.set_inventory(inv_list)

        # Get inventories for the first resource provider and validate
        # the inventory records have a matching resource provider
        got_inv = rp_obj.InventoryList.get_all_by_resource_provider(
                self.ctx, rp1)
        for inv in got_inv:
            self.assertEqual(rp1.id, inv.resource_provider.id)


class ResourceProviderListTestCase(ResourceProviderBaseCase):
    def setUp(self):
        super(ResourceProviderListTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')

    def test_get_all_by_filters(self):
        for rp_i in ['1', '2']:
            uuid = getattr(uuidsentinel, 'rp_uuid_' + rp_i)
            name = 'rp_name_' + rp_i
            rp = rp_obj.ResourceProvider(self.ctx, name=name, uuid=uuid)
            rp.create()

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx)
        self.assertEqual(2, len(resource_providers))
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'uuid': getattr(uuidsentinel, 'rp_uuid_2')})
        self.assertEqual(1, len(resource_providers))
        self.assertEqual('rp_name_2', resource_providers[0].name)

    def test_get_all_by_filters_with_resources(self):
        for rp_i in ['1', '2']:
            uuid = getattr(uuidsentinel, 'rp_uuid_' + rp_i)
            name = 'rp_name_' + rp_i
            rp = rp_obj.ResourceProvider(self.ctx, name=name, uuid=uuid)
            rp.create()
            inv = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.VCPU,
                min_unit=1,
                max_unit=2,
                total=2,
                allocation_ratio=1.0)
            inv.obj_set_defaults()

            inv2 = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.DISK_GB,
                total=1024, reserved=2,
                min_unit=1,
                max_unit=1024,
                allocation_ratio=1.0)
            inv2.obj_set_defaults()

            # Write that specific inventory for testing min/max units and steps
            inv3 = rp_obj.Inventory(
                resource_provider=rp,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024, reserved=2,
                min_unit=2,
                max_unit=4,
                step_size=2,
                allocation_ratio=1.0)
            inv3.obj_set_defaults()

            inv_list = rp_obj.InventoryList(objects=[inv, inv2, inv3])
            rp.set_inventory(inv_list)

            # Create the VCPU allocation only for the first RP
            if rp_i != '1':
                continue
            allocation_1 = rp_obj.Allocation(
                resource_provider=rp,
                consumer_id=uuidsentinel.consumer,
                resource_class=fields.ResourceClass.VCPU,
                used=1)
            allocation_list = rp_obj.AllocationList(
                self.ctx, objects=[allocation_1])
            allocation_list.create_all()

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
            uuid = getattr(uuidsentinel, 'rp_uuid_' + str(rp_i))
            name = 'rp_name_' + str(rp_i)
            rp = rp_obj.ResourceProvider(self.ctx, name=name, uuid=uuid)
            rp.create()
            if rp_i % 2:
                aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
                rp.set_aggregates(aggregate_uuids)

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of': [uuidsentinel.agg_a]})

        self.assertEqual(2, len(resource_providers))
        names = [_rp.name for _rp in resource_providers]
        self.assertIn('rp_name_1', names)
        self.assertIn('rp_name_3', names)
        self.assertNotIn('rp_name_2', names)
        self.assertNotIn('rp_name_4', names)

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b]})
        self.assertEqual(2, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b],
                                   'name': u'rp_name_1'})
        self.assertEqual(1, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [uuidsentinel.agg_a, uuidsentinel.agg_b],
                                   'name': u'barnabas'})
        self.assertEqual(0, len(resource_providers))

        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            self.ctx, filters={'member_of':
                                   [uuidsentinel.agg_1, uuidsentinel.agg_2]})
        self.assertEqual(0, len(resource_providers))


class TestResourceProviderAggregates(test.NoDBTestCase):

    USES_DB_SELF = True

    def setUp(self):
        super(TestResourceProviderAggregates, self).setUp()
        self.useFixture(fixtures.Database(database='main'))
        self.useFixture(fixtures.Database(database='api'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')

    def test_set_and_get_new_aggregates(self):
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
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
        read_rp = rp_obj.ResourceProvider.get_by_uuid(
            self.ctx, uuidsentinel.rp_uuid)
        re_read_aggregate_uuids = read_rp.get_aggregates()
        self.assertItemsEqual(aggregate_uuids, re_read_aggregate_uuids)

    def test_set_aggregates_is_replace(self):
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
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
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.rp_uuid,
            name=uuidsentinel.rp_name
        )
        rp.create()
        start_aggregate_uuids = [uuidsentinel.agg_a, uuidsentinel.agg_b]
        rp.set_aggregates(start_aggregate_uuids)
        aggs = rp.get_aggregates()
        self.assertEqual(2, len(aggs))
        rp.destroy()
        aggs = rp.get_aggregates()
        self.assertEqual(0, len(aggs))


class TestAllocation(ResourceProviderBaseCase):

    def test_create_list_and_delete_allocation(self):
        resource_provider = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.allocation_resource_provider,
            name=uuidsentinel.allocation_resource_name
        )
        resource_provider.create()
        resource_class = fields.ResourceClass.DISK_GB
        inv = rp_obj.Inventory(context=self.ctx,
                resource_provider=resource_provider, **DISK_INVENTORY)
        inv_list = rp_obj.InventoryList(context=self.ctx, objects=[inv])
        resource_provider.set_inventory(inv_list)
        disk_allocation = rp_obj.Allocation(
            context=self.ctx,
            resource_provider=resource_provider,
            **DISK_ALLOCATION
        )
        alloc_list = rp_obj.AllocationList(self.ctx,
                objects=[disk_allocation])
        alloc_list.create_all()

        self.assertEqual(resource_class, disk_allocation.resource_class)
        self.assertEqual(resource_provider,
                         disk_allocation.resource_provider)
        self.assertEqual(DISK_ALLOCATION['used'],
                         disk_allocation.used)
        self.assertEqual(DISK_ALLOCATION['consumer_id'],
                         disk_allocation.consumer_id)

        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, resource_provider)

        self.assertEqual(1, len(allocations))

        self.assertEqual(DISK_ALLOCATION['used'],
                        allocations[0].used)

        allocations.delete_all()

        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, resource_provider)

        self.assertEqual(0, len(allocations))

    def test_multi_provider_allocation(self):
        """Tests that an allocation that includes more than one resource
        provider can be created, listed and deleted properly.

        Bug #1707669 highlighted a situation that arose when attempting to
        remove part of an allocation for a source host during a resize
        operation where the exiting allocation was not being properly
        deleted.
        """
        cn_source = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.cn_source,
            name=uuidsentinel.cn_source,
        )
        cn_source.create()

        cn_dest = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.cn_dest,
            name=uuidsentinel.cn_dest,
        )
        cn_dest.create()

        # Add same inventory to both source and destination host
        for cn in (cn_source, cn_dest):
            cpu_inv = rp_obj.Inventory(
                context=self.ctx,
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0)
            ram_inv = rp_obj.Inventory(
                context=self.ctx,
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=64,
                allocation_ratio=1.5)
            inv_list = rp_obj.InventoryList(context=self.ctx,
                objects=[cpu_inv, ram_inv])
            cn.set_inventory(inv_list)

        # Now create an allocation that represents a move operation where the
        # scheduler has selected cn_dest as the target host and created a
        # "doubled-up" allocation for the duration of the move operation
        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_source,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_source,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
            ])
        alloc_list.create_all()

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
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.VCPU,
                    used=1),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=uuidsentinel.instance,
                    resource_provider=cn_dest,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=256),
            ])
        new_alloc_list.create_all()

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
        rp, allocation = self._make_allocation()
        allocations = rp_obj.AllocationList.get_all_by_resource_provider(
            self.ctx, rp)
        self.assertEqual(1, len(allocations))
        self.assertEqual(rp.id, allocations[0].resource_provider.id)
        self.assertEqual(allocation.resource_provider.id,
                         allocations[0].resource_provider.id)


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

        rp1 = rp_obj.ResourceProvider(
            self.ctx, name=rp1_name, uuid=rp1_uuid)
        rp1.create()

        inv = rp_obj.Inventory(resource_provider=rp1,
                               resource_class=rp1_class,
                               total=1024, max_unit=max_unit)
        inv.obj_set_defaults()

        inv2 = rp_obj.Inventory(resource_provider=rp1,
                                resource_class=rp2_class,
                                total=255, reserved=2,
                                max_unit=max_unit)
        inv2.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv, inv2])
        rp1.set_inventory(inv_list)

        # create the allocations for a first consumer
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])
        allocation_list.create_all()

        # create the allocations for a second consumer, until we have
        # allocations for more than one consumer in the db, then we
        # won't actually be doing real allocation math, which triggers
        # the sql monster.
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid2,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid2,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])
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

        rp1 = rp_obj.ResourceProvider(
            self.ctx, name=rp1_name, uuid=rp1_uuid)
        rp1.create()
        rp2 = rp_obj.ResourceProvider(
            self.ctx, name=rp2_name, uuid=rp2_uuid)
        rp2.create()

        # Two allocations, one for each resource provider.
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_2 = rp_obj.Allocation(resource_provider=rp2,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp2_class,
                                         used=rp2_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1, allocation_2])

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
        inv = rp_obj.Inventory(resource_provider=rp1,
                               resource_class=rp1_class,
                               total=1024)
        inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv])
        rp1.set_inventory(inv_list)
        self.assertRaises(exception.InvalidInventory,
                          allocation_list.create_all)

        # Add inventory for the second resource provider
        inv = rp_obj.Inventory(resource_provider=rp2,
                               resource_class=rp2_class,
                               total=255, reserved=2)
        inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv])
        rp2.set_inventory(inv_list)

        # Now the allocations will still fail because max_unit 1
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          allocation_list.create_all)
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
        allocation_list.create_all()

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
        allocation_1 = rp_obj.Allocation(resource_provider=rp1,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp1_class,
                                         used=rp1_used)
        allocation_list = rp_obj.AllocationList(
            self.ctx, objects=[allocation_1])
        allocation_list.create_all()

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
        rp = rp_obj.ResourceProvider(
            self.ctx, name=rp_name, uuid=rp_uuid)
        rp.create()
        inv = rp_obj.Inventory(resource_provider=rp,
                               total=1024, allocation_ratio=1,
                               reserved=0, **kwargs)
        inv.obj_set_defaults()
        rp.set_inventory(rp_obj.InventoryList(objects=[inv]))
        return rp

    def _validate_usage(self, rp, usage):
        rp_usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, rp.uuid)
        self.assertEqual(usage, rp_usage[0].usage)

    def _check_create_allocations(self, inventory_kwargs,
                                  bad_used, good_used):
        consumer_uuid = uuidsentinel.consumer
        rp_class = fields.ResourceClass.DISK_GB
        rp = self._make_rp_and_inventory(resource_class=rp_class,
                                         **inventory_kwargs)

        # allocation, bad step_size
        allocation = rp_obj.Allocation(resource_provider=rp,
                                       consumer_id=consumer_uuid,
                                       resource_class=rp_class,
                                       used=bad_used)
        allocation_list = rp_obj.AllocationList(self.ctx,
                                                 objects=[allocation])
        self.assertRaises(exception.InvalidAllocationConstraintsViolated,
                          allocation_list.create_all)

        # correct for step size
        allocation.used = good_used
        allocation_list = rp_obj.AllocationList(self.ctx,
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

    def test_create_all_with_project_user(self):
        consumer_uuid = uuidsentinel.consumer
        rp_class = fields.ResourceClass.DISK_GB
        rp = self._make_rp_and_inventory(resource_class=rp_class,
                                         max_unit=500)
        allocation1 = rp_obj.Allocation(resource_provider=rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=100)
        allocation2 = rp_obj.Allocation(resource_provider=rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.create_all()

        # Verify that we have records in the consumers, projects, and users
        # table for the information used in the above allocation creation
        with self.api_db.get_engine().connect() as conn:
            tbl = rp_obj._PROJECT_TBL
            sel = sa.select([tbl.c.id]).where(
                tbl.c.external_id == self.ctx.project_id,
            )
            res = conn.execute(sel).fetchall()
            self.assertEqual(1, len(res), "project lookup not created.")

            tbl = rp_obj._USER_TBL
            sel = sa.select([tbl.c.id]).where(
                tbl.c.external_id == self.ctx.user_id,
            )
            res = conn.execute(sel).fetchall()
            self.assertEqual(1, len(res), "user lookup not created.")

            tbl = rp_obj._CONSUMER_TBL
            sel = sa.select([tbl.c.id]).where(
                tbl.c.uuid == consumer_uuid,
            )
            res = conn.execute(sel).fetchall()
            self.assertEqual(1, len(res), "consumer lookup not created.")

        # Create allocation for a different user in the project
        other_consumer_uuid = uuidsentinel.other_consumer
        allocation3 = rp_obj.Allocation(resource_provider=rp,
                                        consumer_id=other_consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=uuidsentinel.other_user,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation3],
        )
        allocation_list.create_all()

        # Get usages back by project
        usage_list = rp_obj.UsageList.get_all_by_project_user(
            self.ctx, self.ctx.project_id)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(500, usage_list[0].usage)

        # Get usages back by project and user
        usage_list = rp_obj.UsageList.get_all_by_project_user(
            self.ctx, self.ctx.project_id,
            user_id=uuidsentinel.other_user)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(200, usage_list[0].usage)

        # List allocations and confirm project and user
        allocation_list = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, other_consumer_uuid)
        self.assertEqual(1, len(allocation_list))
        allocation = allocation_list[0]
        self.assertEqual(self.ctx.project_id, allocation.project_id)
        self.assertEqual(uuidsentinel.other_user, allocation.user_id)

    def test_create_and_clear(self):
        """Test that a used of 0 in an allocation wipes allocations."""
        consumer_uuid = uuidsentinel.consumer
        rp_class = fields.ResourceClass.DISK_GB
        target_rp = self._make_rp_and_inventory(resource_class=rp_class,
                                                max_unit=500)

        # Create two allocations with values and confirm the resulting
        # usage is as expected.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=100)
        allocation2 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.create_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(2, len(allocations))
        usage = sum(alloc.used for alloc in allocations)
        self.assertEqual(300, usage)

        # Create two allocations, one with 0 used, to confirm the
        # resulting usage is only of one.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp_class,
                                         project_id=self.ctx.project_id,
                                         user_id=self.ctx.user_id,
                                         used=0)
        allocation2 = rp_obj.Allocation(resource_provider=target_rp,
                                         consumer_id=consumer_uuid,
                                         resource_class=rp_class,
                                         project_id=self.ctx.project_id,
                                         user_id=self.ctx.user_id,
                                         used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.create_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        # add a source rp and a migration consumer
        migration_uuid = uuidsentinel.migration
        source_rp = self._make_rp_and_inventory(
            rp_name=uuidsentinel.source_name, rp_uuid=uuidsentinel.source_uuid,
            resource_class=rp_class, max_unit=500)

        # Create two allocations, one as the consumer, one as the
        # migration.
        allocation1 = rp_obj.Allocation(resource_provider=target_rp,
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=200)
        allocation2 = rp_obj.Allocation(resource_provider=source_rp,
                                        consumer_id=migration_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=200)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.create_all()

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
                                        consumer_id=consumer_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=200)
        allocation2 = rp_obj.Allocation(resource_provider=source_rp,
                                        consumer_id=migration_uuid,
                                        resource_class=rp_class,
                                        project_id=self.ctx.project_id,
                                        user_id=self.ctx.user_id,
                                        used=0)
        allocation_list = rp_obj.AllocationList(
            self.ctx,
            objects=[allocation1, allocation2],
        )
        allocation_list.create_all()

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, consumer_uuid)
        self.assertEqual(1, len(allocations))
        usage = allocations[0].used
        self.assertEqual(200, usage)

        allocations = rp_obj.AllocationList.get_all_by_consumer_id(
            self.ctx, migration_uuid)
        self.assertEqual(0, len(allocations))

    @mock.patch('nova.objects.resource_provider.LOG')
    def test_set_allocations_retry(self, mock_log):
        """Test server side allocation write retry handling."""

        # Create a single resource provider and give it some inventory.
        rp1 = rp_obj.ResourceProvider(
            self.ctx, name='rp1', uuid=uuidsentinel.rp1)
        rp1.create()
        add_inventory(rp1, fields.ResourceClass.VCPU, 24,
                      allocation_ratio=16.0)
        add_inventory(rp1, fields.ResourceClass.MEMORY_MB, 1024,
                      min_unit=64,
                      max_unit=1024,
                      step_size=64)
        original_generation = rp1.generation
        # Verify the generation is what we expect (we'll be checking again
        # later).
        self.assertEqual(2, original_generation)

        inst_consumer = uuidsentinel.instance

        alloc_list = rp_obj.AllocationList(context=self.ctx,
            objects=[
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=inst_consumer,
                    resource_provider=rp1,
                    resource_class=fields.ResourceClass.VCPU,
                    used=12),
                rp_obj.Allocation(
                    context=self.ctx,
                    consumer_id=inst_consumer,
                    resource_provider=rp1,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    used=1024)
            ])

        # Make sure the right exception happens when the retry loop expires.
        with mock.patch.object(rp_obj.AllocationList,
                               'RP_CONFLICT_RETRY_COUNT', 0):
            self.assertRaises(
                exception.ResourceProviderConcurrentUpdateDetected,
                alloc_list.create_all)
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
                'nova.objects.resource_provider.'
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
                alloc_list.create_all()
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


class UsageListTestCase(ResourceProviderBaseCase):

    def test_get_all_null(self):
        for uuid in [uuidsentinel.rp_uuid_1, uuidsentinel.rp_uuid_2]:
            rp = rp_obj.ResourceProvider(self.ctx, name=uuid, uuid=uuid)
            rp.create()

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, uuidsentinel.rp_uuid_1)
        self.assertEqual(0, len(usage_list))

    def test_get_all_one_allocation(self):
        db_rp, _ = self._make_allocation(rp_uuid=uuidsentinel.rp_uuid)
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
        db_rp = rp_obj.ResourceProvider(self.ctx,
                                        name=uuidsentinel.rp_no_inv,
                                        uuid=uuidsentinel.rp_no_inv)
        db_rp.create()
        inv = rp_obj.Inventory(resource_provider=db_rp,
                               resource_class=fields.ResourceClass.DISK_GB,
                               total=1024)
        inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[inv])
        db_rp.set_inventory(inv_list)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, db_rp.uuid)
        self.assertEqual(1, len(usage_list))
        self.assertEqual(0, usage_list[0].usage)
        self.assertEqual(fields.ResourceClass.DISK_GB,
                         usage_list[0].resource_class)

    def test_get_all_multiple_inv(self):
        db_rp = rp_obj.ResourceProvider(self.ctx,
                                        name=uuidsentinel.rp_no_inv,
                                        uuid=uuidsentinel.rp_no_inv)
        db_rp.create()
        disk_inv = rp_obj.Inventory(
            resource_provider=db_rp,
            resource_class=fields.ResourceClass.DISK_GB, total=1024)
        disk_inv.obj_set_defaults()
        vcpu_inv = rp_obj.Inventory(
            resource_provider=db_rp,
            resource_class=fields.ResourceClass.VCPU, total=24)
        vcpu_inv.obj_set_defaults()
        inv_list = rp_obj.InventoryList(objects=[disk_inv, vcpu_inv])
        db_rp.set_inventory(inv_list)

        usage_list = rp_obj.UsageList.get_all_by_resource_provider_uuid(
            self.ctx, db_rp.uuid)
        self.assertEqual(2, len(usage_list))


class ResourceClassListTestCase(ResourceProviderBaseCase):

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
        with self.api_db.get_engine().connect() as conn:
            for custom in customs:
                c_name, c_id = custom
                ins = rp_obj._RC_TBL.insert().values(id=c_id, name=c_name)
                conn.execute(ins)

        rcs = rp_obj.ResourceClassList.get_all(self.ctx)
        expected_count = len(fields.ResourceClass.STANDARD) + len(customs)
        self.assertEqual(expected_count, len(rcs))


class ResourceClassTestCase(ResourceProviderBaseCase):

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

    @mock.patch.object(nova.objects.resource_provider.ResourceClass,
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

    @mock.patch.object(nova.objects.resource_provider.ResourceClass,
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


class ResourceProviderTraitTestCase(ResourceProviderBaseCase):

    def setUp(self):
        super(ResourceProviderTraitTestCase, self).setUp()
        # Reset the _TRAITS_SYNCED global before we start and after
        # we are done since other tests (notably the gabbi tests)
        # may have caused it to change.
        self._reset_traits_synced()
        self.addCleanup(self._reset_traits_synced)

    @staticmethod
    def _reset_traits_synced():
        """Reset the _TRAITS_SYNCED boolean to base state."""
        rp_obj._TRAITS_SYNCED = False

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
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        rp.create()
        generation = rp.generation
        self.assertIsInstance(rp.id, int)

        trait_names = ['CUSTOM_TRAIT_A', 'CUSTOM_TRAIT_B', 'CUSTOM_TRAIT_C']
        trait_objs = []
        for name in trait_names:
            t = rp_obj.Trait(self.ctx)
            t.name = name
            t.create()
            trait_objs.append(t)

        rp.set_traits(trait_objs)

        rp_traits = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self._assert_traits(trait_names, rp_traits)
        self.assertEqual(rp.generation, generation + 1)
        generation = rp.generation

        trait_names.remove('CUSTOM_TRAIT_A')
        updated_traits = rp_obj.TraitList.get_all(self.ctx,
            filters={'name_in': trait_names})
        self._assert_traits(trait_names, updated_traits)
        rp.set_traits(updated_traits)
        rp_traits = rp_obj.TraitList.get_all_by_resource_provider(self.ctx, rp)
        self._assert_traits(trait_names, rp_traits)
        self.assertEqual(rp.generation, generation + 1)

    def test_set_traits_for_correct_resource_provider(self):
        """This test creates two ResourceProviders, and attaches same trait to
        both of them. Then detaching the trait from one of them, and ensure
        the trait still associated with another one.
        """
        # Create two ResourceProviders
        rp1 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider1,
            name=uuidsentinel.fake_resource_name1,
        )
        rp1.create()
        rp2 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider2,
            name=uuidsentinel.fake_resource_name2,
        )
        rp2.create()

        # Create a trait
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()

        # Associate the trait with two ResourceProviders
        rp1.set_traits([t])
        rp2.set_traits([t])

        # Ensure the association
        rp1_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp1)
        rp2_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp2)
        self._assert_traits(['CUSTOM_TRAIT_A'], rp1_traits)
        self._assert_traits(['CUSTOM_TRAIT_A'], rp2_traits)

        # Detach the trait from one of ResourceProvider, and ensure the
        # trait association with another ResourceProvider still exists.
        rp1.set_traits([])
        rp1_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp1)
        rp2_traits = rp_obj.TraitList.get_all_by_resource_provider(
            self.ctx, rp2)
        self._assert_traits([], rp1_traits)
        self._assert_traits(['CUSTOM_TRAIT_A'], rp2_traits)

    def test_trait_delete_in_use(self):
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider,
            name=uuidsentinel.fake_resource_name,
        )
        rp.create()
        t = rp_obj.Trait(self.ctx)
        t.name = 'CUSTOM_TRAIT_A'
        t.create()
        rp.set_traits([t])
        self.assertRaises(exception.TraitInUse, t.destroy)

    def test_traits_get_all_with_associated_true(self):
        rp1 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider1,
            name=uuidsentinel.fake_resource_name1,
        )
        rp1.create()
        rp2 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider2,
            name=uuidsentinel.fake_resource_name2,
        )
        rp2.create()
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
        rp1 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider1,
            name=uuidsentinel.fake_resource_name1,
        )
        rp1.create()
        rp2 = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=uuidsentinel.fake_resource_provider2,
            name=uuidsentinel.fake_resource_name2,
        )
        rp2.create()
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

    def test_sync_standard_traits(self):
        """Tests that on a clean DB, we have zero traits in the DB but after
        list all traits, os_traits have been synchronized.
        """
        std_traits = os_traits.get_traits()
        conn = self.api_db.get_engine().connect()

        def _db_traits(conn):
            sel = sa.select([rp_obj._TRAIT_TBL.c.name])
            return [r[0] for r in conn.execute(sel).fetchall()]

        self.assertEqual([], _db_traits(conn))

        all_traits = [trait.name for trait in
                      rp_obj.TraitList.get_all(self.ctx)]
        self.assertEqual(set(std_traits), set(all_traits))
        # confirm with a raw request
        self.assertEqual(set(std_traits), set(_db_traits(conn)))


class SharedProviderTestCase(ResourceProviderBaseCase):
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
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        # Populate the two compute node providers with inventory.  One has
        # DISK_GB.  Both should be excluded from the result (one doesn't have
        # the requested resource; but neither is a sharing provider).
        for cn in (cn1, cn2):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=32768,
                reserved=0,
                min_unit=64,
                max_unit=32768,
                step_size=64,
                allocation_ratio=1.5,
            )
            if cn is cn1:
                disk_gb = rp_obj.Inventory(
                    resource_provider=cn,
                    resource_class=fields.ResourceClass.DISK_GB,
                    total=2000,
                    reserved=0,
                    min_unit=10,
                    max_unit=100,
                    step_size=10,
                    allocation_ratio=1.0,
                )
                inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb,
                                                         disk_gb])
            else:
                inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the shared storage pool
        ss_uuid = uuidsentinel.ss
        ss = rp_obj.ResourceProvider(
            self.ctx,
            name='shared storage',
            uuid=ss_uuid,
        )
        ss.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = rp_obj.Inventory(
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
        inv_list = rp_obj.InventoryList(objects=[disk_gb])
        ss.set_inventory(inv_list)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        t = rp_obj.Trait.get_by_name(self.ctx, "MISC_SHARES_VIA_AGGREGATE")
        ss.set_traits(rp_obj.TraitList(objects=[t]))

        # OK, now that has all been set up, let's verify that we get the ID of
        # the shared storage pool when we ask for DISK_GB
        got_ids = rp_obj._get_providers_with_shared_capacity(
            self.ctx,
            fields.ResourceClass.STANDARD.index(fields.ResourceClass.DISK_GB),
            100,
        )
        self.assertEqual([ss.id], got_ids)

    def test_get_all_with_shared(self):
        """We set up two compute nodes with VCPU and MEMORY_MB only, a shared
        resource provider having DISK_GB inventory, and associate all of them
        with an aggregate. We then call the _get_all_with_shared() function to
        ensure that we get back the two compute node resource provider records.
        """
        # The aggregate that will be associated to everything...
        agg_uuid = uuidsentinel.agg

        # Create the two compute node providers
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        # Populate the two compute node providers with inventory, sans DISK_GB
        for cn in (cn1, cn2):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=1,
                allocation_ratio=1.5,
            )
            inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the shared storage pool
        ss_uuid = uuidsentinel.ss
        ss = rp_obj.ResourceProvider(
            self.ctx,
            name='shared storage',
            uuid=ss_uuid,
        )
        ss.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = rp_obj.Inventory(
            resource_provider=ss,
            resource_class=fields.ResourceClass.DISK_GB,
            total=2000,
            reserved=0,
            min_unit=10,
            max_unit=100,
            step_size=1,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[disk_gb])
        ss.set_inventory(inv_list)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        t = rp_obj.Trait.get_by_name(self.ctx, "MISC_SHARES_VIA_AGGREGATE")
        ss.set_traits(rp_obj.TraitList(objects=[t]))

        resources = self._requested_resources()

        # Before we associate the compute nodes and shared storage provider
        # with the same aggregate, verify that no resource providers are found
        # that meet the requested set of resource amounts
        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([], got_ids)

        # Now associate the shared storage pool and both compute nodes with the
        # same aggregate
        cn1.set_aggregates([agg_uuid])
        cn2.set_aggregates([agg_uuid])
        ss.set_aggregates([agg_uuid])

        # OK, now that has all been set up, let's verify that we get the ID of
        # the shared storage pool when we ask for some DISK_GB
        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([cn1.id, cn2.id], got_ids)

        # Now we add another compute node that has vCPU and RAM along with
        # local disk and is *not* associated with the agg1. We want to verify
        # that this compute node, because it has all three resources "locally"
        # is also returned by _get_all_with_shared() along with the other
        # compute nodes that are associated with the shared storage pool.
        cn3_uuid = uuidsentinel.cn3
        cn3 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn3',
            uuid=cn3_uuid,
        )
        cn3.create()
        vcpu = rp_obj.Inventory(
            resource_provider=cn3,
            resource_class=fields.ResourceClass.VCPU,
            total=24,
            reserved=0,
            min_unit=1,
            max_unit=24,
            step_size=1,
            allocation_ratio=1.0,
        )
        memory_mb = rp_obj.Inventory(
            resource_provider=cn3,
            resource_class=fields.ResourceClass.MEMORY_MB,
            total=1024,
            reserved=0,
            min_unit=64,
            max_unit=1024,
            step_size=1,
            allocation_ratio=1.0,
        )
        disk_gb = rp_obj.Inventory(
            resource_provider=cn3,
            resource_class=fields.ResourceClass.DISK_GB,
            total=500,
            reserved=0,
            min_unit=10,
            max_unit=500,
            step_size=10,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb, disk_gb])
        cn3.set_inventory(inv_list)

        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([cn1.id, cn2.id, cn3.id], got_ids)

        # Consume all vCPU and RAM inventory on the "local disk" compute node
        # and verify it no longer is returned from _get_all_with_shared()

        vcpu_alloc = rp_obj.Allocation(
            resource_provider=cn3,
            resource_class=fields.ResourceClass.VCPU,
            consumer_id=uuidsentinel.consumer,
            used=24,
        )
        memory_mb_alloc = rp_obj.Allocation(
            resource_provider=cn3,
            resource_class=fields.ResourceClass.MEMORY_MB,
            consumer_id=uuidsentinel.consumer,
            used=1024,
        )

        alloc_list = rp_obj.AllocationList(
            self.ctx,
            objects=[vcpu_alloc, memory_mb_alloc]
        )
        alloc_list.create_all()

        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([cn1.id, cn2.id], got_ids)

        # Now we consume all the memory in the second compute node and verify
        # that it does not get returned from _get_all_with_shared()

        for x in range(3):
            # allocation_ratio for MEMORY_MB is 1.5, so we need to make 3
            # 512-MB allocations to fully consume the memory on the node
            memory_mb_alloc = rp_obj.Allocation(
                resource_provider=cn2,
                resource_class=fields.ResourceClass.MEMORY_MB,
                consumer_id=getattr(uuidsentinel, 'consumer%d' % x),
                used=512,
            )
            alloc_list = rp_obj.AllocationList(
                self.ctx,
                objects=[memory_mb_alloc]
            )
            alloc_list.create_all()

        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([cn1.id], got_ids)

        # Create another two compute node providers having no local disk
        # inventory and associated with a different aggregate. Then create a
        # storage provider but do NOT decorate that provider with the
        # MISC_SHARES_VIA_AGGREGATE trait and verify that neither of the new
        # compute node providers are returned by _get_all_with_shared()

        cn4_uuid = uuidsentinel.cn4
        cn4 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn4',
            uuid=cn4_uuid,
        )
        cn4.create()

        cn5_uuid = uuidsentinel.cn5
        cn5 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn5',
            uuid=cn5_uuid,
        )
        cn5.create()

        # Populate the two compute node providers with inventory, sans DISK_GB
        for cn in (cn4, cn5):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=1,
                allocation_ratio=1.5,
            )
            inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the storage provider but do NOT mark it sharing its inventory
        # with other providers
        ns_uuid = uuidsentinel.ns
        ns = rp_obj.ResourceProvider(
            self.ctx,
            name='non_shared storage',
            uuid=ns_uuid,
        )
        ns.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = rp_obj.Inventory(
            resource_provider=ns,
            resource_class=fields.ResourceClass.DISK_GB,
            total=2000,
            reserved=0,
            min_unit=10,
            max_unit=100,
            step_size=1,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[disk_gb])
        ns.set_inventory(inv_list)

        # Associate the new no-local-disk compute nodes and the non-shared
        # storage provider with an aggregate that is different from the
        # aggregate associating the shared storage provider with compute nodes
        agg2_uuid = uuidsentinel.agg2
        cn4.set_aggregates([agg2_uuid])
        cn5.set_aggregates([agg2_uuid])
        ns.set_aggregates([agg2_uuid])

        # Ensure neither cn4 nor cn5 are in the returned providers list,
        # because neither has DISK_GB inventory and although they are
        # associated with an aggregate that has a storage provider with DISK_GB
        # inventory, that storage provider is not marked as sharing that
        # DISK_GB inventory with anybody.
        got_rps = rp_obj._get_all_with_shared(
            self.ctx,
            resources,
        )
        got_ids = [rp.id for rp in got_rps]
        self.assertEqual([cn1.id], got_ids)
