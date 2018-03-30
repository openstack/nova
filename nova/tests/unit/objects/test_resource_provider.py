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
import six

import nova
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.objects import resource_provider
from nova import test
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


_RESOURCE_CLASS_NAME = 'DISK_GB'
_RESOURCE_CLASS_ID = 2
IPV4_ADDRESS_ID = objects.fields.ResourceClass.STANDARD.index(
    fields.ResourceClass.IPV4_ADDRESS)
VCPU_ID = objects.fields.ResourceClass.STANDARD.index(
    fields.ResourceClass.VCPU)

_RESOURCE_PROVIDER_ID = 1
_RESOURCE_PROVIDER_UUID = uuids.resource_provider
_RESOURCE_PROVIDER_NAME = six.text_type(uuids.resource_name)
_RESOURCE_PROVIDER_DB = {
    'id': _RESOURCE_PROVIDER_ID,
    'uuid': _RESOURCE_PROVIDER_UUID,
    'name': _RESOURCE_PROVIDER_NAME,
    'generation': 0,
}
_INVENTORY_ID = 2
_INVENTORY_DB = {
    'id': _INVENTORY_ID,
    'resource_provider_id': _RESOURCE_PROVIDER_ID,
    'resource_class_id': _RESOURCE_CLASS_ID,
    'total': 16,
    'reserved': 2,
    'min_unit': 1,
    'max_unit': 8,
    'step_size': 1,
    'allocation_ratio': 1.0,
}
_ALLOCATION_ID = 2
_ALLOCATION_DB = {
    'id': _ALLOCATION_ID,
    'resource_provider_id': _RESOURCE_PROVIDER_ID,
    'resource_class_id': _RESOURCE_CLASS_ID,
    'consumer_id': uuids.fake_instance,
    'used': 8,
}


def _fake_ensure_cache(ctxt):
    cache = resource_provider._RC_CACHE = mock.MagicMock()
    cache.string_from_id.return_value = _RESOURCE_CLASS_NAME
    cache.id_from_string.return_value = _RESOURCE_CLASS_ID


class TestResourceProviderNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.ResourceProvider._get_by_uuid_from_db',
                return_value=_RESOURCE_PROVIDER_DB)
    def test_object_get_by_uuid(self, mock_db_get):
        resource_provider_object = objects.ResourceProvider.get_by_uuid(
            mock.sentinel.ctx, _RESOURCE_PROVIDER_UUID)
        self.assertEqual(_RESOURCE_PROVIDER_ID, resource_provider_object.id)
        self.assertEqual(_RESOURCE_PROVIDER_UUID,
                         resource_provider_object.uuid)

    @mock.patch('nova.objects.ResourceProvider._create_in_db',
                return_value=_RESOURCE_PROVIDER_DB)
    def test_create(self, mock_db_create):
        obj = objects.ResourceProvider(context=self.context,
                                       uuid=_RESOURCE_PROVIDER_UUID,
                                       name=_RESOURCE_PROVIDER_NAME)
        obj.create()
        self.assertEqual(_RESOURCE_PROVIDER_UUID, obj.uuid)
        self.assertIsInstance(obj.id, int)
        mock_db_create.assert_called_once_with(
            self.context, {'uuid': _RESOURCE_PROVIDER_UUID,
                           'name': _RESOURCE_PROVIDER_NAME})

    def test_create_id_fail(self):
        obj = objects.ResourceProvider(context=self.context,
                                       uuid=_RESOURCE_PROVIDER_UUID,
                                       id=_RESOURCE_PROVIDER_ID)
        self.assertRaises(exception.ObjectActionError,
                          obj.create)

    def test_create_no_uuid_fail(self):
        obj = objects.ResourceProvider(context=self.context)
        self.assertRaises(exception.ObjectActionError,
                          obj.create)


class TestResourceProvider(test_objects._LocalTest):

    def test_create_in_db(self):
        updates = {'uuid': _RESOURCE_PROVIDER_UUID,
                   'name': _RESOURCE_PROVIDER_NAME}
        db_rp = objects.ResourceProvider._create_in_db(
            self.context, updates)
        self.assertIsInstance(db_rp.id, int)
        self.assertEqual(_RESOURCE_PROVIDER_UUID, db_rp.uuid)
        self.assertEqual(_RESOURCE_PROVIDER_NAME, db_rp.name)

    def test_save_immutable(self):
        fields = {'id': 1, 'uuid': _RESOURCE_PROVIDER_UUID,
                  'generation': 1}
        for field in fields:
            rp = objects.ResourceProvider(context=self.context)
            setattr(rp, field, fields[field])
            self.assertRaises(exception.ObjectActionError, rp.save)

    def test_get_by_uuid_from_db(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=_RESOURCE_PROVIDER_UUID,
                                      name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        retrieved_rp = objects.ResourceProvider._get_by_uuid_from_db(
            self.context, _RESOURCE_PROVIDER_UUID)
        self.assertEqual(rp.uuid, retrieved_rp.uuid)
        self.assertEqual(rp.name, retrieved_rp.name)

    def test_get_by_uuid_from_db_missing(self):
        self.assertRaises(exception.NotFound,
                          objects.ResourceProvider.get_by_uuid,
                          self.context, uuids.missing)

    def test_destroy_with_traits(self):
        """Test deleting a resource provider that has a trait successfully.
        """
        rp = resource_provider.ResourceProvider(self.context,
                                                uuid=uuids.rp,
                                                name='fake_rp1')
        rp.create()
        custom_trait = resource_provider.Trait(self.context,
                                               uuid=uuids.trait,
                                               name='CUSTOM_TRAIT_1')
        custom_trait.create()
        rp.set_traits([custom_trait])

        trl = rp.get_traits()
        self.assertEqual(1, len(trl))

        # Delete a resource provider that has a trait assosiation.
        rp.destroy()

        # Assert the record has been deleted
        # in 'resource_provider_traits' table
        # after Resource Provider object has been destroyed.
        trl = rp.get_traits()
        self.assertEqual(0, len(trl))
        # Assert that NotFound exception is raised.
        self.assertRaises(exception.NotFound,
                          resource_provider.ResourceProvider.get_by_uuid,
                          self.context, uuids.rp)


class TestInventoryNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.Inventory._create_in_db',
                return_value=_INVENTORY_DB)
    def test_create(self, mock_db_create, mock_ensure_cache):
        rp = objects.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                      uuid=_RESOURCE_PROVIDER_UUID)
        obj = objects.Inventory(context=self.context,
                                resource_provider=rp,
                                resource_class=_RESOURCE_CLASS_NAME,
                                total=16,
                                reserved=2,
                                min_unit=1,
                                max_unit=8,
                                step_size=1,
                                allocation_ratio=1.0)
        obj.create()
        self.assertEqual(_INVENTORY_ID, obj.id)
        expected = dict(_INVENTORY_DB)
        expected.pop('id')
        mock_db_create.assert_called_once_with(self.context, expected)

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.Inventory._update_in_db',
                return_value=_INVENTORY_DB)
    def test_save(self, mock_db_save, mock_ensure_cache):
        obj = objects.Inventory(context=self.context,
                                id=_INVENTORY_ID,
                                reserved=4)
        obj.save()
        mock_db_save.assert_called_once_with(self.context,
                                             _INVENTORY_ID,
                                             {'reserved': 4})

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.InventoryList._get_all_by_resource_provider')
    def test_get_all_by_resource_provider(self, mock_get, mock_ensure_cache):
        expected = [dict(_INVENTORY_DB,
                         resource_provider=dict(_RESOURCE_PROVIDER_DB)),
                    dict(_INVENTORY_DB,
                         id=_INVENTORY_DB['id'] + 1,
                         resource_provider=dict(_RESOURCE_PROVIDER_DB))]
        mock_get.return_value = expected
        objs = objects.InventoryList.get_all_by_resource_provider_uuid(
            self.context, _RESOURCE_PROVIDER_DB['uuid'])
        self.assertEqual(2, len(objs))
        self.assertEqual(_INVENTORY_DB['id'], objs[0].id)
        self.assertEqual(_INVENTORY_DB['id'] + 1, objs[1].id)

    def test_non_negative_handling(self):
        # NOTE(cdent): Just checking, useless to be actually
        # comprehensive here.
        rp = objects.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                      uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16,
                      reserved=2,
                      min_unit=1,
                      max_unit=-8,
                      step_size=1,
                      allocation_ratio=1.0)
        self.assertRaises(ValueError, objects.Inventory,
                          **kwargs)

    def test_set_defaults(self):
        rp = objects.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                      uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16)
        inv = objects.Inventory(self.context, **kwargs)

        inv.obj_set_defaults()
        self.assertEqual(0, inv.reserved)
        self.assertEqual(1, inv.min_unit)
        self.assertEqual(1, inv.max_unit)
        self.assertEqual(1, inv.step_size)
        self.assertEqual(1.0, inv.allocation_ratio)

    def test_capacity(self):
        rp = objects.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                      uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16,
                      reserved=16)
        inv = objects.Inventory(self.context, **kwargs)
        inv.obj_set_defaults()

        self.assertEqual(0, inv.capacity)
        inv.reserved = 15
        self.assertEqual(1, inv.capacity)
        inv.allocation_ratio = 2.0
        self.assertEqual(2, inv.capacity)


class TestInventory(test_objects._LocalTest):

    def _make_inventory(self, rp_uuid=None):
        uuid = rp_uuid or uuids.inventory_resource_provider
        name = uuid
        db_rp = objects.ResourceProvider(
            context=self.context, uuid=uuid, name=name)
        db_rp.create()
        db_inventory = self._create_inventory_in_db(db_rp.id)
        return db_rp, db_inventory

    def _create_inventory_in_db(self, rp_id, **records):
        updates = dict(_INVENTORY_DB,
                       resource_provider_id=rp_id)
        updates.pop('id')
        updates.update(records)
        return objects.Inventory._create_in_db(
            self.context, updates)

    def test_create_in_db(self):
        updates = dict(_INVENTORY_DB)
        updates.pop('id')
        db_inventory = objects.Inventory._create_in_db(
            self.context, updates)
        self.assertEqual(_INVENTORY_DB['total'], db_inventory.total)

    def test_update_in_db(self):
        db_rp, db_inventory = self._make_inventory()
        objects.Inventory._update_in_db(self.context,
                                        db_inventory.id,
                                        {'total': 32})
        inventories = objects.InventoryList.\
            get_all_by_resource_provider_uuid(self.context, db_rp.uuid)
        self.assertEqual(32, inventories[0].total)

    def test_update_in_db_fails_bad_id(self):
        db_rp, db_inventory = self._make_inventory()
        self.assertRaises(exception.NotFound,
                          objects.Inventory._update_in_db,
                          self.context, 99, {'total': 32})

    def test_get_all_by_resource_provider_uuid(self):
        db_rp, db_inventory = self._make_inventory()

        retrieved_inventories = (
            objects.InventoryList._get_all_by_resource_provider(
                self.context, db_rp.uuid)
        )

        self.assertEqual(1, len(retrieved_inventories))
        self.assertEqual(db_inventory.id, retrieved_inventories[0].id)
        self.assertEqual(db_inventory.total, retrieved_inventories[0].total)

        retrieved_inventories = (
            objects.InventoryList._get_all_by_resource_provider(
                self.context, uuids.bad_rp_uuid)
        )
        self.assertEqual(0, len(retrieved_inventories))

    def test_get_all_by_resource_provider_multiple_providers(self):
        # TODO(cdent): This and other nearby tests are functional
        # and should be moved.
        # Create 2 resource providers with DISK_GB resources. And
        # update total value for second one.
        db_rp1, db_inv1 = self._make_inventory(uuids.fake_1)
        db_rp2, db_inv2 = self._make_inventory(uuids.fake_2)

        objects.Inventory._update_in_db(self.context,
                                        db_inv2.id,
                                        {'total': 32})

        # Create IPV4_ADDRESS resources for each provider.
        self._create_inventory_in_db(db_rp1.id,
                                     resource_provider_id=db_rp1.id,
                                     resource_class_id=IPV4_ADDRESS_ID,
                                     total=2)
        self._create_inventory_in_db(db_rp2.id,
                                     resource_provider_id=db_rp2.id,
                                     resource_class_id=IPV4_ADDRESS_ID,
                                     total=4)

        expected_inv1 = {
            _RESOURCE_CLASS_ID: _INVENTORY_DB['total'],
            IPV4_ADDRESS_ID: 2}
        expected_inv2 = {
            _RESOURCE_CLASS_ID: 32,
            IPV4_ADDRESS_ID: 4}

        # Get inventories for each resource provider and validate
        # that the inventory records for that resource provider uuid
        # and match expected total value.
        retrieved_inv = (
            objects.InventoryList._get_all_by_resource_provider(
                self.context, db_rp1.uuid)
        )
        for inv in retrieved_inv:
            self.assertEqual(db_rp1.id, inv.resource_provider_id)
            self.assertEqual(expected_inv1[inv.resource_class_id],
                             inv.total)

        retrieved_inv = (
            objects.InventoryList._get_all_by_resource_provider(
                self.context, db_rp2.uuid)
        )

        for inv in retrieved_inv:
            self.assertEqual(db_rp2.id, inv.resource_provider_id)
            self.assertEqual(expected_inv2[inv.resource_class_id],
                             inv.total)

    def test_create_requires_resource_provider(self):
        inventory_dict = dict(_INVENTORY_DB)
        inventory_dict.pop('id')
        inventory_dict.pop('resource_provider_id')
        inventory_dict.pop('resource_class_id')
        inventory_dict['resource_class'] = _RESOURCE_CLASS_NAME
        inventory = objects.Inventory(context=self.context,
                                      **inventory_dict)
        error = self.assertRaises(exception.ObjectActionError,
                                  inventory.create)
        self.assertIn('resource_provider required', str(error))

    def test_create_requires_created_resource_provider(self):
        rp = objects.ResourceProvider(
            context=self.context, uuid=uuids.inventory_resource_provider)
        inventory_dict = dict(_INVENTORY_DB)
        inventory_dict.pop('id')
        inventory_dict.pop('resource_provider_id')
        inventory_dict.pop('resource_class_id')
        inventory_dict['resource_provider'] = rp
        inventory = objects.Inventory(context=self.context,
                                      **inventory_dict)
        error = self.assertRaises(exception.ObjectActionError,
                                  inventory.create)
        self.assertIn('resource_provider required', str(error))

    def test_create_requires_resource_class(self):
        rp = objects.ResourceProvider(
            context=self.context, uuid=uuids.inventory_resource_provider,
            name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        inventory_dict = dict(_INVENTORY_DB)
        inventory_dict.pop('id')
        inventory_dict.pop('resource_provider_id')
        inventory_dict.pop('resource_class_id')
        inventory_dict['resource_provider'] = rp
        inventory = objects.Inventory(context=self.context,
                                      **inventory_dict)
        error = self.assertRaises(exception.ObjectActionError,
                                  inventory.create)
        self.assertIn('resource_class required', str(error))

    def test_create_id_fails(self):
        inventory = objects.Inventory(self.context, **_INVENTORY_DB)
        self.assertRaises(exception.ObjectActionError, inventory.create)

    def test_save_without_id_fails(self):
        inventory_dict = dict(_INVENTORY_DB)
        inventory_dict.pop('id')
        inventory = objects.Inventory(self.context, **inventory_dict)
        self.assertRaises(exception.ObjectActionError, inventory.save)

    def test_find(self):
        rp = objects.ResourceProvider(uuid=uuids.rp_uuid)
        inv_list = objects.InventoryList(objects=[
                objects.Inventory(
                    resource_provider=rp,
                    resource_class=fields.ResourceClass.VCPU,
                    total=24),
                objects.Inventory(
                    resource_provider=rp,
                    resource_class=fields.ResourceClass.MEMORY_MB,
                    total=10240),
        ])

        found = inv_list.find(fields.ResourceClass.MEMORY_MB)
        self.assertIsNotNone(found)
        self.assertEqual(10240, found.total)

        found = inv_list.find(fields.ResourceClass.VCPU)
        self.assertIsNotNone(found)
        self.assertEqual(24, found.total)

        found = inv_list.find(fields.ResourceClass.DISK_GB)
        self.assertIsNone(found)

        # Try an integer resource class identifier...
        self.assertRaises(ValueError, inv_list.find, VCPU_ID)

        # Use an invalid string...
        self.assertIsNone(inv_list.find('HOUSE'))

    def test_custom_resource_raises(self):
        """Ensure that if we send an inventory object to a backversioned 1.0
        receiver, that we raise ValueError if the inventory record contains a
        custom (non-standardized) resource class.
        """
        values = {
            # NOTE(danms): We don't include an actual resource provider
            # here because chained backporting of that is handled by
            # the infrastructure and requires us to have a manifest
            'resource_class': 'custom_resource',
            'total': 1,
            'reserved': 0,
            'min_unit': 1,
            'max_unit': 1,
            'step_size': 1,
            'allocation_ratio': 1.0,
        }
        bdm = objects.Inventory(context=self.context, **values)
        self.assertRaises(ValueError,
                          bdm.obj_to_primitive,
                          target_version='1.0')


class TestAllocation(test_objects._LocalTest):
    USES_DB = True

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    def test_create(self, mock_ensure_cache):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=_RESOURCE_PROVIDER_UUID,
                                      name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        inv = objects.Inventory(context=self.context,
                                resource_provider=rp,
                                resource_class=_RESOURCE_CLASS_NAME,
                                total=16,
                                reserved=2,
                                min_unit=1,
                                max_unit=8,
                                step_size=1,
                                allocation_ratio=1.0)
        inv.create()
        obj = objects.Allocation(context=self.context,
                                 resource_provider=rp,
                                 resource_class=_RESOURCE_CLASS_NAME,
                                 consumer_id=uuids.fake_instance,
                                 used=8)
        alloc_list = objects.AllocationList(self.context, objects=[obj])
        alloc_list.create_all()

        rp_al = resource_provider.AllocationList
        saved_allocations = rp_al.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)
        self.assertEqual(1, len(saved_allocations))
        self.assertEqual(obj.used, saved_allocations[0].used)

    def test_create_with_id_fails(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=_RESOURCE_PROVIDER_UUID,
                                      name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        inv = objects.Inventory(context=self.context,
                                resource_provider=rp,
                                resource_class=_RESOURCE_CLASS_NAME,
                                total=16,
                                reserved=2,
                                min_unit=1,
                                max_unit=8,
                                step_size=1,
                                allocation_ratio=1.0)
        inv.create()
        obj = objects.Allocation(context=self.context,
                                 id=99,
                                 resource_provider=rp,
                                 resource_class=_RESOURCE_CLASS_NAME,
                                 consumer_id=uuids.fake_instance,
                                 used=8)
        alloc_list = objects.AllocationList(self.context, objects=[obj])
        self.assertRaises(exception.ObjectActionError, alloc_list.create_all)


class TestAllocationNoDB(test_objects._LocalTest):
    USES_DB = False

    def test_custom_resource_raises(self):
        """Ensure that if we send an inventory object to a backversioned 1.0
        receiver, that we raise ValueError if the inventory record contains a
        custom (non-standardized) resource class.
        """
        values = {
            # NOTE(danms): We don't include an actual resource provider
            # here because chained backporting of that is handled by
            # the infrastructure and requires us to have a manifest
            'resource_class': 'custom_resource',
            'consumer_id': uuids.consumer_id,
            'used': 1,
        }
        bdm = objects.Allocation(context=self.context, **values)
        self.assertRaises(ValueError,
                          bdm.obj_to_primitive,
                          target_version='1.0')


class TestAllocationListNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.AllocationList._get_allocations_from_db',
                return_value=[_ALLOCATION_DB])
    def test_get_allocations(self, mock_get_allocations_from_db,
            mock_ensure_cache):
        rp = objects.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                      uuid=uuids.resource_provider)
        allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
            self.context, rp.uuid)

        self.assertEqual(1, len(allocations))
        mock_get_allocations_from_db.assert_called_once_with(
            self.context, resource_provider_uuid=uuids.resource_provider)
        self.assertEqual(_ALLOCATION_DB['used'], allocations[0].used)


class TestUsageNoDB(test_objects._LocalTest):
    USES_DB = False

    def test_v1_1_resource_class(self):
        usage = objects.Usage(resource_class='foo')
        self.assertRaises(ValueError,
                          usage.obj_to_primitive,
                          target_version='1.0')


class TestResourceClass(test.NoDBTestCase):

    def setUp(self):
        super(TestResourceClass, self).setUp()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_cannot_create_with_id(self):
        rc = objects.ResourceClass(self.context, id=1, name='CUSTOM_IRON_NFV')
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('already created', str(exc))

    def test_cannot_create_requires_name(self):
        rc = objects.ResourceClass(self.context)
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('name is required', str(exc))


class TestTraitSync(test_objects._LocalTest):
    @mock.patch("nova.objects.resource_provider._trait_sync")
    def test_sync_flag(self, mock_sync):
        synced = nova.objects.resource_provider._TRAITS_SYNCED
        self.assertFalse(synced)
        # Sync the traits
        nova.objects.resource_provider._ensure_trait_sync(self.context)
        synced = nova.objects.resource_provider._TRAITS_SYNCED
        self.assertTrue(synced)
