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
from oslo_utils import uuidutils

from nova import exception
from nova import objects
from nova.objects import cell_mapping
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


def get_db_mapping(**updates):
    db_mapping = {
            'id': 1,
            'uuid': uuidutils.generate_uuid(),
            'name': 'cell1',
            'transport_url': 'rabbit://',
            'database_connection': 'sqlite:///',
            'created_at': None,
            'updated_at': None,
            }
    db_mapping.update(updates)
    return db_mapping


class _TestCellMappingObject(object):
    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_get_by_uuid(self, uuid_from_db):
        db_mapping = get_db_mapping()
        uuid_from_db.return_value = db_mapping

        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        uuid_from_db.assert_called_once_with(self.context, db_mapping['uuid'])
        self.compare_obj(mapping_obj, db_mapping)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db',
                       side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_get_by_uuid_invalid(self, uuid_from_db):
        db_mapping = get_db_mapping()
        self.assertRaises(exception.CellMappingNotFound,
                          objects.CellMapping().get_by_uuid,
                          self.context,
                          db_mapping['uuid'])
        uuid_from_db.assert_called_once_with(self.context, db_mapping['uuid'])

    @mock.patch.object(cell_mapping.CellMapping, '_create_in_db')
    def test_create(self, create_in_db):
        uuid = uuidutils.generate_uuid()
        db_mapping = get_db_mapping(uuid=uuid, name='test',
                database_connection='mysql+pymysql:///')
        create_in_db.return_value = db_mapping
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid
        mapping_obj.name = 'test'
        mapping_obj.database_connection = 'mysql+pymysql:///'

        mapping_obj.create()
        create_in_db.assert_called_once_with(self.context,
                {'uuid': uuid,
                 'name': 'test',
                 'database_connection': 'mysql+pymysql:///'})
        self.compare_obj(mapping_obj, db_mapping)

    @mock.patch.object(cell_mapping.CellMapping, '_save_in_db')
    def test_save(self, save_in_db):
        uuid = uuidutils.generate_uuid()
        db_mapping = get_db_mapping(database_connection='mysql+pymysql:///')
        save_in_db.return_value = db_mapping
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid
        mapping_obj.database_connection = 'mysql+pymysql:///'

        mapping_obj.save()
        save_in_db.assert_called_once_with(self.context, uuid,
                {'uuid': uuid,
                 'database_connection': 'mysql+pymysql:///'})
        self.compare_obj(mapping_obj, db_mapping)

    @mock.patch.object(cell_mapping.CellMapping, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        uuid = uuidutils.generate_uuid()
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid

        mapping_obj.destroy()
        destroy_in_db.assert_called_once_with(self.context, uuid)

    def test_is_cell0(self):
        self.assertFalse(objects.CellMapping().is_cell0())
        self.assertFalse(objects.CellMapping(
            uuid=uuidutils.generate_uuid()).is_cell0())
        self.assertTrue(objects.CellMapping(
            uuid=objects.CellMapping.CELL0_UUID).is_cell0())

    def test_identity_no_name_set(self):
        cm = objects.CellMapping(uuid=uuids.cell1)
        self.assertEqual(uuids.cell1, cm.identity)

    def test_identity_name_is_none(self):
        cm = objects.CellMapping(uuid=uuids.cell1)
        self.assertEqual(uuids.cell1, cm.identity)

    def test_identity_with_name(self):
        cm = objects.CellMapping(uuid=uuids.cell1, name='foo')
        self.assertEqual('%s(foo)' % uuids.cell1, cm.identity)


class TestCellMappingObject(test_objects._LocalTest,
                            _TestCellMappingObject):
    pass


class TestRemoteCellMappingObject(test_objects._RemoteTest,
                                  _TestCellMappingObject):
    pass


class _TestCellMappingListObject(object):
    @mock.patch.object(cell_mapping.CellMappingList, '_get_all_from_db')
    def test_get_all(self, get_all_from_db):
        db_mapping = get_db_mapping()
        get_all_from_db.return_value = [db_mapping]

        mapping_obj = objects.CellMappingList.get_all(self.context)

        get_all_from_db.assert_called_once_with(self.context)
        self.compare_obj(mapping_obj.objects[0], db_mapping)

    def test_get_all_sorted(self):
        for ident in (10, 3):
            cm = objects.CellMapping(context=self.context,
                                     id=ident,
                                     uuid=getattr(uuids, 'cell%i' % ident),
                                     transport_url='fake://%i' % ident,
                                     database_connection='fake://%i' % ident)
            cm.create()
        obj = objects.CellMappingList.get_all(self.context)
        ids = [c.id for c in obj]
        # Find the two normal cells, plus the two we created, but in the right
        # order
        self.assertEqual([1, 2, 3, 10], ids)


class TestCellMappingListObject(test_objects._LocalTest,
                                _TestCellMappingListObject):
    pass


class TestRemoteCellMappingListObject(test_objects._RemoteTest,
                                      _TestCellMappingListObject):
    pass
