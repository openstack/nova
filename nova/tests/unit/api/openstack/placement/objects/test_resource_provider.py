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
from oslo_utils import timeutils
import six
import testtools

from nova.api.openstack.placement import context
from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import resource_provider
from nova import rc_fields as fields
from nova.tests import uuidsentinel as uuids


_RESOURCE_CLASS_NAME = 'DISK_GB'
_RESOURCE_CLASS_ID = 2
IPV4_ADDRESS_ID = fields.ResourceClass.STANDARD.index(
    fields.ResourceClass.IPV4_ADDRESS)
VCPU_ID = fields.ResourceClass.STANDARD.index(
    fields.ResourceClass.VCPU)

_RESOURCE_PROVIDER_ID = 1
_RESOURCE_PROVIDER_UUID = uuids.resource_provider
_RESOURCE_PROVIDER_NAME = six.text_type(uuids.resource_name)
_RESOURCE_PROVIDER_DB = {
    'id': _RESOURCE_PROVIDER_ID,
    'uuid': _RESOURCE_PROVIDER_UUID,
    'name': _RESOURCE_PROVIDER_NAME,
    'generation': 0,
    'root_provider_uuid': _RESOURCE_PROVIDER_UUID,
    'parent_provider_uuid': None,
    'updated_at': None,
    'created_at': timeutils.utcnow(with_timezone=True),
}

_RESOURCE_PROVIDER_ID2 = 2
_RESOURCE_PROVIDER_UUID2 = uuids.resource_provider2
_RESOURCE_PROVIDER_NAME2 = uuids.resource_name2
_RESOURCE_PROVIDER_DB2 = {
    'id': _RESOURCE_PROVIDER_ID2,
    'uuid': _RESOURCE_PROVIDER_UUID2,
    'name': _RESOURCE_PROVIDER_NAME2,
    'generation': 0,
    'root_provider_uuid': _RESOURCE_PROVIDER_UUID,
    'parent_provider_uuid': _RESOURCE_PROVIDER_UUID,
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
    'updated_at': None,
    'created_at': timeutils.utcnow(with_timezone=True),
}
_ALLOCATION_ID = 2
_ALLOCATION_DB = {
    'id': _ALLOCATION_ID,
    'resource_provider_id': _RESOURCE_PROVIDER_ID,
    'resource_class_id': _RESOURCE_CLASS_ID,
    'consumer_uuid': uuids.fake_instance,
    'consumer_id': 1,
    'consumer_generation': 0,
    'used': 8,
    'user_id': 1,
    'user_external_id': uuids.user_id,
    'project_id': 1,
    'project_external_id': uuids.project_id,
}


def _fake_ensure_cache(ctxt):
    cache = resource_provider._RC_CACHE = mock.MagicMock()
    cache.string_from_id.return_value = _RESOURCE_CLASS_NAME
    cache.id_from_string.return_value = _RESOURCE_CLASS_ID


class _TestCase(testtools.TestCase):
    """Base class for other tests in this file.

    It establishes the RequestContext used as self.context in the tests.
    """

    def setUp(self):
        super(_TestCase, self).setUp()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)


class TestResourceProviderNoDB(_TestCase):

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

    def test_create_with_root_provider_uuid_fail(self):
        obj = resource_provider.ResourceProvider(
            context=self.context,
            uuid=_RESOURCE_PROVIDER_UUID,
            name=_RESOURCE_PROVIDER_NAME,
            root_provider_uuid=_RESOURCE_PROVIDER_UUID,
        )

        exc = self.assertRaises(exception.ObjectActionError, obj.create)
        self.assertIn('root provider UUID cannot be manually set', str(exc))

    def test_save_immutable(self):
        fields = {
            'id': 1,
            'uuid': _RESOURCE_PROVIDER_UUID,
            'generation': 1,
            'root_provider_uuid': _RESOURCE_PROVIDER_UUID,
        }
        for field in fields:
            rp = resource_provider.ResourceProvider(context=self.context)
            setattr(rp, field, fields[field])
            self.assertRaises(exception.ObjectActionError, rp.save)


class TestProviderSummaryNoDB(_TestCase):

    def test_resource_class_names(self):
        psum = resource_provider.ProviderSummary(mock.sentinel.ctx)
        disk_psr = resource_provider.ProviderSummaryResource(
            mock.sentinel.ctx, resource_class=fields.ResourceClass.DISK_GB,
            capacity=100, used=0)
        ram_psr = resource_provider.ProviderSummaryResource(
            mock.sentinel.ctx, resource_class=fields.ResourceClass.MEMORY_MB,
            capacity=1024, used=0)
        psum.resources = [disk_psr, ram_psr]
        expected = set(['DISK_GB', 'MEMORY_MB'])
        self.assertEqual(expected, psum.resource_class_names)


class TestInventoryNoDB(_TestCase):

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                'ensure_rc_cache', side_effect=_fake_ensure_cache)
    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                '_get_inventory_by_provider_id')
    def test_get_all_by_resource_provider(self, mock_get, mock_ensure_cache):
        mock_ensure_cache(self.context)
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


class TestInventoryList(_TestCase):

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


class TestAllocationListNoDB(_TestCase):

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                '_create_incomplete_consumers_for_provider')
    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                'ensure_rc_cache',
                side_effect=_fake_ensure_cache)
    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                '_get_allocations_by_provider_id',
                return_value=[_ALLOCATION_DB])
    def test_get_allocations(self, mock_get_allocations_from_db,
            mock_ensure_cache, mock_create_consumers):
        mock_ensure_cache(self.context)
        rp = resource_provider.ResourceProvider(id=_RESOURCE_PROVIDER_ID,
                                                uuid=uuids.resource_provider)
        rp_alloc_list = resource_provider.AllocationList
        allocations = rp_alloc_list.get_all_by_resource_provider(
            self.context, rp)

        self.assertEqual(1, len(allocations))
        mock_get_allocations_from_db.assert_called_once_with(self.context,
            rp.id)
        self.assertEqual(_ALLOCATION_DB['used'], allocations[0].used)
        mock_create_consumers.assert_called_once_with(
            self.context, _RESOURCE_PROVIDER_ID)


class TestResourceClass(_TestCase):

    def test_cannot_create_with_id(self):
        rc = resource_provider.ResourceClass(self.context, id=1,
                                             name='CUSTOM_IRON_NFV')
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('already created', str(exc))

    def test_cannot_create_requires_name(self):
        rc = resource_provider.ResourceClass(self.context)
        exc = self.assertRaises(exception.ObjectActionError, rc.create)
        self.assertIn('name is required', str(exc))


class TestTraits(_TestCase):

    @mock.patch("nova.api.openstack.placement.objects.resource_provider."
                "_trait_sync")
    def test_sync_flag(self, mock_sync):
        synced = resource_provider._TRAITS_SYNCED
        self.assertFalse(synced)
        # Sync the traits
        resource_provider.ensure_trait_sync(self.context)
        synced = resource_provider._TRAITS_SYNCED
        self.assertTrue(synced)

    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                'ResourceProvider.obj_reset_changes')
    @mock.patch('nova.api.openstack.placement.objects.resource_provider.'
                '_set_traits')
    def test_set_traits_resets_changes(self, mock_set_traits, mock_reset):
        trait = resource_provider.Trait(name="HW_CPU_X86_AVX2")
        traits = resource_provider.TraitList(objects=[trait])

        rp = resource_provider.ResourceProvider(self.context, name='cn1',
            uuid=uuids.cn1)
        rp.set_traits(traits)
        mock_set_traits.assert_called_once_with(self.context, rp, traits)
        mock_reset.assert_called_once_with()
