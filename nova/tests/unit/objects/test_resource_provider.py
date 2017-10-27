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
    'user_id': None,
    'project_id': None,
}


def _fake_ensure_cache(ctxt):
    cache = resource_provider._RC_CACHE = mock.MagicMock()
    cache.string_from_id.return_value = _RESOURCE_CLASS_NAME
    cache.id_from_string.return_value = _RESOURCE_CLASS_ID


class TestResourceProviderNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.resource_provider._get_provider_by_uuid',
                return_value=_RESOURCE_PROVIDER_DB)
    def test_object_get_by_uuid(self, mock_db_get):
        resource_provider_object = resource_provider.ResourceProvider.\
            get_by_uuid(mock.sentinel.ctx, _RESOURCE_PROVIDER_UUID)
        self.assertEqual(_RESOURCE_PROVIDER_ID, resource_provider_object.id)
        self.assertEqual(_RESOURCE_PROVIDER_UUID,
                         resource_provider_object.uuid)

    @mock.patch('nova.objects.resource_provider.ResourceProvider.'
                '_create_in_db', return_value=_RESOURCE_PROVIDER_DB)
    def test_create(self, mock_db_create):
        obj = resource_provider.ResourceProvider(context=self.context,
                                                 uuid=_RESOURCE_PROVIDER_UUID,
                                                 name=_RESOURCE_PROVIDER_NAME)
        obj.create()
        self.assertEqual(_RESOURCE_PROVIDER_UUID, obj.uuid)
        self.assertIsInstance(obj.id, int)
        mock_db_create.assert_called_once_with(
            self.context, {'uuid': _RESOURCE_PROVIDER_UUID,
                           'name': _RESOURCE_PROVIDER_NAME})

    def test_create_id_fail(self):
        obj = resource_provider.ResourceProvider(context=self.context,
                                                 uuid=_RESOURCE_PROVIDER_UUID,
                                                 id=_RESOURCE_PROVIDER_ID)
        self.assertRaises(exception.ObjectActionError,
                          obj.create)

    def test_create_no_uuid_fail(self):
        obj = resource_provider.ResourceProvider(context=self.context)
        self.assertRaises(exception.ObjectActionError,
                          obj.create)


class TestResourceProvider(test_objects._LocalTest):

    def test_create_in_db(self):
        updates = {'uuid': _RESOURCE_PROVIDER_UUID,
                   'name': _RESOURCE_PROVIDER_NAME}
        db_rp = resource_provider.ResourceProvider._create_in_db(
            self.context, updates)
        self.assertIsInstance(db_rp.id, int)
        self.assertEqual(_RESOURCE_PROVIDER_UUID, db_rp.uuid)
        self.assertEqual(_RESOURCE_PROVIDER_NAME, db_rp.name)

    def test_save_immutable(self):
        fields = {'id': 1, 'uuid': _RESOURCE_PROVIDER_UUID,
                  'generation': 1}
        for field in fields:
            rp = resource_provider.ResourceProvider(context=self.context)
            setattr(rp, field, fields[field])
            self.assertRaises(exception.ObjectActionError, rp.save)

    def test_get_by_uuid_from_db(self):
        rp = resource_provider.ResourceProvider(context=self.context,
                                                uuid=_RESOURCE_PROVIDER_UUID,
                                                name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        retrieved_rp = resource_provider.ResourceProvider.get_by_uuid(
            self.context, _RESOURCE_PROVIDER_UUID)
        self.assertEqual(rp.uuid, retrieved_rp.uuid)
        self.assertEqual(rp.name, retrieved_rp.name)

    def test_get_by_uuid_from_db_missing(self):
        self.assertRaises(exception.NotFound,
                          resource_provider.ResourceProvider.get_by_uuid,
                          self.context, uuids.missing)


class TestInventoryNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
                side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.resource_provider._get_inventory_by_provider_id')
    def test_get_all_by_resource_provider(self, mock_get, mock_ensure_cache):
        expected = [dict(_INVENTORY_DB,
                         resource_provider_id=_RESOURCE_PROVIDER_ID),
                    dict(_INVENTORY_DB,
                         id=_INVENTORY_DB['id'] + 1,
                         resource_provider_id=_RESOURCE_PROVIDER_ID)]
        mock_get.return_value = expected
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=_RESOURCE_PROVIDER_UUID)
        objs = resource_provider.InventoryList.get_all_by_resource_provider(
            self.context, rp)
        self.assertEqual(2, len(objs))
        self.assertEqual(_INVENTORY_DB['id'], objs[0].id)
        self.assertEqual(_INVENTORY_DB['id'] + 1, objs[1].id)
        self.assertEqual(_RESOURCE_PROVIDER_ID, objs[0].resource_provider.id)

    def test_non_negative_handling(self):
        # NOTE(cdent): Just checking, useless to be actually
        # comprehensive here.
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16,
                      reserved=2,
                      min_unit=1,
                      max_unit=-8,
                      step_size=1,
                      allocation_ratio=1.0)
        self.assertRaises(ValueError, resource_provider.Inventory,
                          **kwargs)

    def test_set_defaults(self):
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16)
        inv = resource_provider.Inventory(self.context, **kwargs)

        inv.obj_set_defaults()
        self.assertEqual(0, inv.reserved)
        self.assertEqual(1, inv.min_unit)
        self.assertEqual(1, inv.max_unit)
        self.assertEqual(1, inv.step_size)
        self.assertEqual(1.0, inv.allocation_ratio)

    def test_capacity(self):
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=_RESOURCE_PROVIDER_UUID)
        kwargs = dict(resource_provider=rp,
                      resource_class=_RESOURCE_CLASS_NAME,
                      total=16,
                      reserved=16)
        inv = resource_provider.Inventory(self.context, **kwargs)
        inv.obj_set_defaults()

        self.assertEqual(0, inv.capacity)
        inv.reserved = 15
        self.assertEqual(1, inv.capacity)
        inv.allocation_ratio = 2.0
        self.assertEqual(2, inv.capacity)


class TestInventoryList(test_objects._LocalTest):

    def test_find(self):
        rp = resource_provider.ResourceProvider(uuid=uuids.rp_uuid)
        inv_list = resource_provider.InventoryList(objects=[
                resource_provider.Inventory(
                    resource_provider=rp,
                    resource_class=fields.ResourceClass.VCPU,
                    total=24),
                resource_provider.Inventory(
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


class TestAllocation(test_objects._LocalTest):
    USES_DB = True

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    def test_create(self, mock_ensure_cache):
        rp = resource_provider.ResourceProvider(context=self.context,
                                                uuid=_RESOURCE_PROVIDER_UUID,
                                                name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        inv = resource_provider.Inventory(context=self.context,
                                          resource_provider=rp,
                                          resource_class=_RESOURCE_CLASS_NAME,
                                          total=16,
                                          reserved=2,
                                          min_unit=1,
                                          max_unit=8,
                                          step_size=1,
                                          allocation_ratio=1.0)
        inv_list = resource_provider.InventoryList(context=self.context,
                                                   objects=[inv])
        rp.set_inventory(inv_list)
        obj = resource_provider.Allocation(context=self.context,
                                           resource_provider=rp,
                                           resource_class=_RESOURCE_CLASS_NAME,
                                           consumer_id=uuids.fake_instance,
                                           used=8)
        alloc_list = resource_provider.AllocationList(self.context,
                                                      objects=[obj])
        self.assertNotIn("id", obj)
        alloc_list.create_all()
        self.assertIn("id", obj)

    def test_create_with_id_fails(self):
        rp = resource_provider.ResourceProvider(context=self.context,
                                                uuid=_RESOURCE_PROVIDER_UUID,
                                                name=_RESOURCE_PROVIDER_NAME)
        rp.create()
        inv = resource_provider.Inventory(context=self.context,
                                resource_provider=rp,
                                resource_class=_RESOURCE_CLASS_NAME,
                                total=16,
                                reserved=2,
                                min_unit=1,
                                max_unit=8,
                                step_size=1,
                                allocation_ratio=1.0)
        inv_list = resource_provider.InventoryList(context=self.context,
                                                   objects=[inv])
        rp.set_inventory(inv_list)
        obj = resource_provider.Allocation(context=self.context,
                                           id=99,
                                           resource_provider=rp,
                                           resource_class=_RESOURCE_CLASS_NAME,
                                           consumer_id=uuids.fake_instance,
                                           used=8)
        alloc_list = resource_provider.AllocationList(self.context,
                                                      objects=[obj])
        self.assertRaises(exception.ObjectActionError, alloc_list.create_all)


class TestAllocationListNoDB(test_objects._LocalTest):
    USES_DB = False

    @mock.patch('nova.objects.resource_provider._ensure_rc_cache',
            side_effect=_fake_ensure_cache)
    @mock.patch('nova.objects.resource_provider.'
                '_get_allocations_by_provider_id',
                return_value=[_ALLOCATION_DB])
    def test_get_allocations(self, mock_get_allocations_from_db,
            mock_ensure_cache):
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=uuids.resource_provider)
        rp_alloc_list = resource_provider.AllocationList
        allocations = rp_alloc_list.get_all_by_resource_provider(
            self.context, rp)

        self.assertEqual(1, len(allocations))
        mock_get_allocations_from_db.assert_called_once_with(self.context,
            rp.id)
        self.assertEqual(_ALLOCATION_DB['used'], allocations[0].used)


class TestResourceClass(test.NoDBTestCase):

    def setUp(self):
        super(TestResourceClass, self).setUp()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_cannot_create_with_id(self):
        rc = resource_provider.ResourceClass(self.context, id=1,
                                             name='CUSTOM_IRON_NFV')
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('already created', str(exc))

    def test_cannot_create_requires_name(self):
        rc = resource_provider.ResourceClass(self.context)
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('name is required', str(exc))


class TestTraits(test.NoDBTestCase):

    def setUp(self):
        super(TestTraits, self).setUp()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    @mock.patch("nova.objects.resource_provider._trait_sync")
    def test_sync_flag(self, mock_sync):
        synced = nova.objects.resource_provider._TRAITS_SYNCED
        self.assertFalse(synced)
        # Sync the traits
        nova.objects.resource_provider._ensure_trait_sync(self.context)
        synced = nova.objects.resource_provider._TRAITS_SYNCED
        self.assertTrue(synced)

    @mock.patch('nova.objects.resource_provider.ResourceProvider.'
                'obj_reset_changes')
    @mock.patch('nova.objects.resource_provider._set_traits')
    def test_set_traits_resets_changes(self, mock_set_traits, mock_reset):
        trait = resource_provider.Trait(name="HW_CPU_X86_AVX2")
        traits = resource_provider.TraitList(objects=[trait])

        rp = resource_provider.ResourceProvider(self.context, name='cn1',
            uuid=uuids.cn1)
        rp.set_traits(traits)
        mock_set_traits.assert_called_once_with(self.context, rp, traits)
        mock_reset.assert_called_once_with()
