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

from nova import objects
from nova.objects import host_mapping
from nova.tests.unit.objects import test_cell_mapping
from nova.tests.unit.objects import test_objects


def get_db_mapping(mapped_cell=None, **updates):
    db_mapping = {
            'id': 1,
            'cell_id': None,
            'host': 'fake-host',
            'created_at': None,
            'updated_at': None,
            }
    if mapped_cell:
        db_mapping["cell_mapping"] = mapped_cell
    else:
        db_mapping["cell_mapping"] = test_cell_mapping.get_db_mapping(id=42)
    db_mapping['cell_id'] = db_mapping["cell_mapping"]["id"]
    db_mapping.update(updates)
    return db_mapping


class _TestHostMappingObject(object):
    def _check_cell_map_value(self, db_val, cell_obj):
        self.assertEqual(db_val, cell_obj.id)

    @mock.patch.object(host_mapping.HostMapping,
            '_get_by_host_from_db')
    def test_get_by_host(self, host_from_db):
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        host_from_db.return_value = db_mapping

        mapping_obj = objects.HostMapping().get_by_host(
                self.context, db_mapping['host'])
        host_from_db.assert_called_once_with(self.context,
                db_mapping['host'])
        with mock.patch.object(
                host_mapping.HostMapping, '_get_cell_mapping') as mock_load:
            self.compare_obj(mapping_obj, db_mapping,
                             subs={'cell_mapping': 'cell_id'},
                             comparators={
                                 'cell_mapping': self._check_cell_map_value})
            # Check that lazy loading isn't happening
            self.failIf(mock_load.called)

    def test_from_db_object_no_cell_map(self):
        """Test when db object does not have cell_mapping"""
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        # If db object has no cell_mapping, lazy loading should occur
        db_mapping.pop("cell_mapping")
        fake_cell_obj = objects.CellMapping(self.context, **fake_cell)

        mapping_obj = objects.HostMapping()._from_db_object(
                self.context, objects.HostMapping(), db_mapping)
        with mock.patch.object(
                host_mapping.HostMapping, '_get_cell_mapping') as mock_load:
            mock_load.return_value = fake_cell_obj
            self.compare_obj(mapping_obj, db_mapping,
                             subs={'cell_mapping': 'cell_id'},
                             comparators={
                                 'cell_mapping': self._check_cell_map_value})
            # Check that cell_mapping is lazy loaded
            mock_load.assert_called_once_with()

    @mock.patch.object(host_mapping.HostMapping, '_create_in_db')
    def test_create(self, create_in_db):
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        db_mapping.pop("cell_mapping")
        host = db_mapping['host']
        create_in_db.return_value = db_mapping

        fake_cell_obj = objects.CellMapping(self.context, **fake_cell)
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = host
        mapping_obj.cell_mapping = fake_cell_obj
        mapping_obj.create()

        create_in_db.assert_called_once_with(self.context,
                {'host': host,
                 'cell_id': fake_cell["id"]})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(host_mapping.HostMapping, '_save_in_db')
    def test_save(self, save_in_db):
        db_mapping = get_db_mapping()
        # This isn't needed here
        db_mapping.pop("cell_mapping")
        host = db_mapping['host']
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = host
        new_fake_cell = test_cell_mapping.get_db_mapping(id=10)
        fake_cell_obj = objects.CellMapping(self.context, **new_fake_cell)
        mapping_obj.cell_mapping = fake_cell_obj
        db_mapping.update({"cell_id": new_fake_cell["id"]})
        save_in_db.return_value = db_mapping

        mapping_obj.save()
        save_in_db.assert_called_once_with(self.context,
                db_mapping['host'],
                {'cell_id': new_fake_cell["id"],
                 'host': host})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(host_mapping.HostMapping, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = "fake-host2"

        mapping_obj.destroy()
        destroy_in_db.assert_called_once_with(self.context, "fake-host2")


class TestHostMappingObject(test_objects._LocalTest,
                            _TestHostMappingObject):
    pass


class TestRemoteHostMappingObject(test_objects._RemoteTest,
                                  _TestHostMappingObject):
    pass
