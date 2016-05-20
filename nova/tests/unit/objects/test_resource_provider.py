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

from nova import exception
from nova import objects
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


_RESOURCE_CLASS_NAME = 'DISK_GB'
_RESOURCE_CLASS_ID = 2
_RESOURCE_PROVIDER_ID = 1
_RESOURCE_PROVIDER_UUID = uuids.resource_provider
_RESOURCE_PROVIDER_DB = {
    'id': _RESOURCE_PROVIDER_ID,
    'uuid': _RESOURCE_PROVIDER_UUID,
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


class _TestResourceProviderNoDB(object):

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
                                       uuid=_RESOURCE_PROVIDER_UUID)
        obj.create()
        self.assertEqual(_RESOURCE_PROVIDER_UUID, obj.uuid)
        self.assertIsInstance(obj.id, int)
        mock_db_create.assert_called_once_with(
            self.context, {'uuid': _RESOURCE_PROVIDER_UUID})

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


class TestResourceProviderNoDB(test_objects._LocalTest,
                               _TestResourceProviderNoDB):
    USES_DB = False


class TestRemoteResourceProviderNoDB(test_objects._RemoteTest,
                                     _TestResourceProviderNoDB):
    USES_DB = False


class TestResourceProvider(test_objects._LocalTest):

    def test_create_in_db(self):
        updates = {'uuid': _RESOURCE_PROVIDER_UUID}
        db_rp = objects.ResourceProvider._create_in_db(
            self.context, updates)
        self.assertIsInstance(db_rp.id, int)
        self.assertEqual(_RESOURCE_PROVIDER_UUID, db_rp.uuid)

    def test_get_by_uuid_from_db(self):
        rp = objects.ResourceProvider(context=self.context,
                                      uuid=_RESOURCE_PROVIDER_UUID)
        rp.create()
        retrieved_rp = objects.ResourceProvider._get_by_uuid_from_db(
            self.context, _RESOURCE_PROVIDER_UUID)
        self.assertEqual(rp.uuid, retrieved_rp.uuid)

        self.assertRaises(exception.NotFound,
                          objects.ResourceProvider._get_by_uuid_from_db,
                          self.context,
                          uuids.missing)


class _TestInventoryNoDB(object):
    @mock.patch('nova.objects.Inventory._create_in_db',
                return_value=_INVENTORY_DB)
    def test_create(self, mock_db_create):
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

    @mock.patch('nova.objects.Inventory._update_in_db',
                return_value=_INVENTORY_DB)
    def test_save(self, mock_db_save):
        obj = objects.Inventory(context=self.context,
                                id=_INVENTORY_ID,
                                reserved=4)
        obj.save()
        mock_db_save.assert_called_once_with(self.context,
                                             _INVENTORY_ID,
                                             {'reserved': 4})

    @mock.patch('nova.objects.InventoryList._get_all_by_resource_provider')
    def test_get_all_by_resource_provider(self, mock_get):
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


class TestInventoryNoDB(test_objects._LocalTest,
                        _TestInventoryNoDB):
    USES_DB = False


class TestRemoteInventoryNoDB(test_objects._RemoteTest,
                              _TestInventoryNoDB):
    USES_DB = False


class TestInventory(test_objects._LocalTest):

    def _make_inventory(self):
        db_rp = objects.ResourceProvider(
            context=self.context, uuid=uuids.inventory_resource_provider)
        db_rp.create()
        updates = dict(_INVENTORY_DB,
                       resource_provider_id=db_rp.id)
        updates.pop('id')
        db_inventory = objects.Inventory._create_in_db(
            self.context, updates)
        return db_rp, db_inventory

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
            context=self.context, uuid=uuids.inventory_resource_provider)
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
