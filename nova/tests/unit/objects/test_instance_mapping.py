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
from nova.objects import instance_mapping
from nova.tests.unit.objects import test_cell_mapping
from nova.tests.unit.objects import test_objects


def get_db_mapping(**updates):
    db_mapping = {
            'id': 1,
            'instance_uuid': uuidutils.generate_uuid(),
            'cell_id': None,
            'project_id': 'fake-project',
            'created_at': None,
            'updated_at': None,
            'queued_for_delete': False,
            }
    db_mapping["cell_mapping"] = test_cell_mapping.get_db_mapping(id=42)
    db_mapping['cell_id'] = db_mapping["cell_mapping"]["id"]
    db_mapping.update(updates)
    return db_mapping


class _TestInstanceMappingObject(object):
    def _check_cell_map_value(self, db_val, cell_obj):
        self.assertEqual(db_val, cell_obj.id)

    @mock.patch.object(instance_mapping.InstanceMapping,
            '_get_by_instance_uuid_from_db')
    def test_get_by_instance_uuid(self, uuid_from_db):
        db_mapping = get_db_mapping()
        uuid_from_db.return_value = db_mapping

        mapping_obj = objects.InstanceMapping().get_by_instance_uuid(
                self.context, db_mapping['instance_uuid'])
        uuid_from_db.assert_called_once_with(self.context,
                db_mapping['instance_uuid'])
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(instance_mapping.InstanceMapping,
            '_get_by_instance_uuid_from_db')
    def test_get_by_instance_uuid_cell_mapping_none(self, uuid_from_db):
        db_mapping = get_db_mapping(cell_mapping=None, cell_id=None)
        uuid_from_db.return_value = db_mapping

        mapping_obj = objects.InstanceMapping().get_by_instance_uuid(
                self.context, db_mapping['instance_uuid'])
        uuid_from_db.assert_called_once_with(self.context,
                db_mapping['instance_uuid'])
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'})

    @mock.patch.object(instance_mapping.InstanceMapping, '_create_in_db')
    def test_create(self, create_in_db):
        db_mapping = get_db_mapping()
        uuid = db_mapping['instance_uuid']
        create_in_db.return_value = db_mapping
        mapping_obj = objects.InstanceMapping(self.context)
        mapping_obj.instance_uuid = uuid
        mapping_obj.cell_mapping = objects.CellMapping(self.context,
                id=db_mapping['cell_mapping']['id'])
        mapping_obj.project_id = db_mapping['project_id']

        mapping_obj.create()
        create_in_db.assert_called_once_with(self.context,
                {'instance_uuid': uuid,
                 'queued_for_delete': False,
                 'cell_id': db_mapping['cell_mapping']['id'],
                 'project_id': db_mapping['project_id']})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(instance_mapping.InstanceMapping, '_create_in_db')
    def test_create_cell_mapping_none(self, create_in_db):
        db_mapping = get_db_mapping(cell_mapping=None, cell_id=None)
        uuid = db_mapping['instance_uuid']
        create_in_db.return_value = db_mapping
        mapping_obj = objects.InstanceMapping(self.context)
        mapping_obj.instance_uuid = uuid
        mapping_obj.cell_mapping = None
        mapping_obj.project_id = db_mapping['project_id']

        mapping_obj.create()
        create_in_db.assert_called_once_with(self.context,
                {'instance_uuid': uuid,
                 'queued_for_delete': False,
                 'project_id': db_mapping['project_id']})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'})
        self.assertIsNone(mapping_obj.cell_mapping)

    @mock.patch.object(instance_mapping.InstanceMapping, '_create_in_db')
    def test_create_cell_mapping_with_qfd_true(self, create_in_db):
        db_mapping = get_db_mapping(cell_mapping=None, cell_id=None)
        create_in_db.return_value = db_mapping
        mapping_obj = objects.InstanceMapping(self.context)
        mapping_obj.instance_uuid = db_mapping['instance_uuid']
        mapping_obj.cell_mapping = None
        mapping_obj.project_id = db_mapping['project_id']
        mapping_obj.queued_for_delete = True

        mapping_obj.create()
        create_in_db.assert_called_once_with(self.context,
                {'instance_uuid': db_mapping['instance_uuid'],
                 'queued_for_delete': True,
                 'project_id': db_mapping['project_id']})

    @mock.patch.object(instance_mapping.InstanceMapping, '_save_in_db')
    def test_save(self, save_in_db):
        db_mapping = get_db_mapping()
        uuid = db_mapping['instance_uuid']
        save_in_db.return_value = db_mapping
        mapping_obj = objects.InstanceMapping(self.context)
        mapping_obj.instance_uuid = uuid
        mapping_obj.cell_mapping = objects.CellMapping(self.context, id=42)

        mapping_obj.save()
        save_in_db.assert_called_once_with(self.context,
                db_mapping['instance_uuid'],
                {'cell_id': mapping_obj.cell_mapping.id,
                 'instance_uuid': uuid})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(instance_mapping.InstanceMapping, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        uuid = uuidutils.generate_uuid()
        mapping_obj = objects.InstanceMapping(self.context)
        mapping_obj.instance_uuid = uuid

        mapping_obj.destroy()
        destroy_in_db.assert_called_once_with(self.context, uuid)

    def test_cell_mapping_nullable(self):
        mapping_obj = objects.InstanceMapping(self.context)
        # Just ensure this doesn't raise an exception
        mapping_obj.cell_mapping = None

    def test_obj_make_compatible(self):
        uuid = uuidutils.generate_uuid()
        im_obj = instance_mapping.InstanceMapping(context=self.context)
        fake_im_obj = instance_mapping.InstanceMapping(context=self.context,
                                                       instance_uuid=uuid,
                                                       queued_for_delete=False)
        obj_primitive = fake_im_obj.obj_to_primitive('1.0')
        obj = im_obj.obj_from_primitive(obj_primitive)
        self.assertIn('instance_uuid', obj)
        self.assertEqual(uuid, obj.instance_uuid)
        self.assertNotIn('queued_for_delete', obj)


class TestInstanceMappingObject(test_objects._LocalTest,
                                _TestInstanceMappingObject):
    pass


class TestRemoteInstanceMappingObject(test_objects._RemoteTest,
                                      _TestInstanceMappingObject):
    pass


class _TestInstanceMappingListObject(object):
    def _check_cell_map_value(self, db_val, cell_obj):
        self.assertEqual(db_val, cell_obj.id)

    @mock.patch.object(instance_mapping.InstanceMappingList,
            '_get_by_project_id_from_db')
    def test_get_by_project_id(self, project_id_from_db):
        db_mapping = get_db_mapping()
        project_id_from_db.return_value = [db_mapping]

        mapping_obj = objects.InstanceMappingList().get_by_project_id(
                self.context, db_mapping['project_id'])
        project_id_from_db.assert_called_once_with(self.context,
                db_mapping['project_id'])
        self.compare_obj(mapping_obj.objects[0], db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(instance_mapping.InstanceMappingList,
                                        '_destroy_bulk_in_db')
    def test_destroy_bulk(self, destroy_bulk_in_db):
        uuids_to_be_deleted = []
        for i in range(0, 5):
            uuid = uuidutils.generate_uuid()
            uuids_to_be_deleted.append(uuid)
        destroy_bulk_in_db.return_value = 5
        result = objects.InstanceMappingList.destroy_bulk(self.context,
                                            uuids_to_be_deleted)
        destroy_bulk_in_db.assert_called_once_with(self.context,
                                            uuids_to_be_deleted)
        self.assertEqual(5, result)


class TestInstanceMappingListObject(test_objects._LocalTest,
                                    _TestInstanceMappingListObject):
    pass


class TestRemoteInstanceMappingListObject(test_objects._RemoteTest,
                                          _TestInstanceMappingListObject):
    pass
