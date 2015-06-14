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

from nova import objects
from nova.objects import cell_mapping
from nova.tests.unit.objects import test_objects


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

    @mock.patch.object(cell_mapping.CellMapping, '_create_in_db')
    def test_create(self, create_in_db):
        uuid = uuidutils.generate_uuid()
        db_mapping = get_db_mapping(uuid=uuid, name='test',
                database_connection='mysql:///')
        create_in_db.return_value = db_mapping
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid
        mapping_obj.name = 'test'
        mapping_obj.database_connection = 'mysql:///'

        mapping_obj.create()
        create_in_db.assert_called_once_with(self.context,
                {'uuid': uuid,
                 'name': 'test',
                 'database_connection': 'mysql:///'})
        self.compare_obj(mapping_obj, db_mapping)

    @mock.patch.object(cell_mapping.CellMapping, '_save_in_db')
    def test_save(self, save_in_db):
        uuid = uuidutils.generate_uuid()
        db_mapping = get_db_mapping(database_connection='mysql:///')
        save_in_db.return_value = db_mapping
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid
        mapping_obj.database_connection = 'mysql:///'

        mapping_obj.save()
        save_in_db.assert_called_once_with(self.context, uuid,
                {'uuid': uuid,
                 'database_connection': 'mysql:///'})
        self.compare_obj(mapping_obj, db_mapping)

    @mock.patch.object(cell_mapping.CellMapping, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        uuid = uuidutils.generate_uuid()
        mapping_obj = objects.CellMapping(self.context)
        mapping_obj.uuid = uuid

        mapping_obj.destroy()
        destroy_in_db.assert_called_once_with(self.context, uuid)


class TestCellMappingObject(test_objects._LocalTest,
                            _TestCellMappingObject):
    pass


class TestRemoteCellMappingObject(test_objects._RemoteTest,
                                  _TestCellMappingObject):
    pass
