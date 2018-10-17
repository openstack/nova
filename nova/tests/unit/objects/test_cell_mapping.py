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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils

from nova import exception
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
            'disabled': False,
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

    def test_obj_make_compatible(self):
        cell_mapping_obj = cell_mapping.CellMapping(context=self.context)
        fake_cell_mapping_obj = cell_mapping.CellMapping(context=self.context,
                                                         uuid=uuids.cell,
                                                         disabled=False)
        obj_primitive = fake_cell_mapping_obj.obj_to_primitive('1.0')
        obj = cell_mapping_obj.obj_from_primitive(obj_primitive)
        self.assertIn('uuid', obj)
        self.assertEqual(uuids.cell, obj.uuid)
        self.assertNotIn('disabled', obj)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_db_url(self, mock_get):
        url = 'sqlite://bob:s3kret@localhost:123/nova?munchies=doritos#baz'
        varurl = ('{scheme}://not{username}:{password}@'
                  '{hostname}:1{port}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(connection=url, group='database')
        db_mapping = get_db_mapping(database_connection=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('sqlite://notbob:s3kret@localhost:1123/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.database_connection)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_mq_url(self, mock_get):
        url = 'rabbit://bob:s3kret@localhost:123/nova?munchies=doritos#baz'
        varurl = ('{scheme}://not{username}:{password}@'
                  '{hostname}:1{port}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=url)
        db_mapping = get_db_mapping(transport_url=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('rabbit://notbob:s3kret@localhost:1123/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_mq_url_multi_netloc1(self, mock_get):
        # Multiple netlocs, each with all parameters
        url = ('rabbit://alice:n0ts3kret@otherhost:456,'
               'bob:s3kret@localhost:123'
               '/nova?munchies=doritos#baz')
        varurl = ('{scheme}://not{username2}:{password1}@'
                  '{hostname2}:1{port1}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=url)
        db_mapping = get_db_mapping(transport_url=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('rabbit://notbob:n0ts3kret@localhost:1456/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_mq_url_multi_netloc1_but_ipv6(self, mock_get):
        # Multiple netlocs, each with all parameters
        url = ('rabbit://alice:n0ts3kret@otherhost:456,'
               'bob:s3kret@[1:2::7]:123'
               '/nova?munchies=doritos#baz')
        varurl = ('{scheme}://not{username2}:{password1}@'
                  '[{hostname2}]:1{port1}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=url)
        db_mapping = get_db_mapping(transport_url=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('rabbit://notbob:n0ts3kret@[1:2::7]:1456/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_mq_url_multi_netloc2(self, mock_get):
        # Multiple netlocs, without optional password and port
        url = ('rabbit://alice@otherhost,'
               'bob:s3kret@localhost:123'
               '/nova?munchies=doritos#baz')
        varurl = ('{scheme}://not{username1}:{password2}@'
                  '{hostname2}:1{port2}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=url)
        db_mapping = get_db_mapping(transport_url=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('rabbit://notalice:s3kret@localhost:1123/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_mq_url_multi_netloc3(self, mock_get):
        # Multiple netlocs, without optional args
        url = ('rabbit://otherhost,'
               'bob:s3kret@localhost:123'
               '/nova?munchies=doritos#baz')
        varurl = ('{scheme}://not{username2}:{password2}@'
                  '{hostname1}:1{port2}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=url)
        db_mapping = get_db_mapping(transport_url=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(('rabbit://notbob:s3kret@otherhost:1123/nova?'
                          'munchies=doritos&flavor=coolranch#baz'),
                         mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    def test_formatted_url_without_base_set(self, mock_get):
        # Make sure we just pass through the template URL if the base
        # URLs are not set
        varurl = ('{scheme}://not{username2}:{password2}@'
                  '{hostname1}:1{port2}/{path}?{query}&flavor=coolranch'
                  '#{fragment}')
        self.flags(transport_url=None)
        self.flags(connection=None, group='database')
        db_mapping = get_db_mapping(transport_url=varurl,
                                    database_connection=varurl)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(varurl, mapping_obj.database_connection)
        self.assertEqual(varurl, mapping_obj.transport_url)

    @mock.patch.object(cell_mapping.CellMapping, '_get_by_uuid_from_db')
    @mock.patch.object(cell_mapping.CellMapping, '_format_url')
    def test_non_formatted_url_with_no_base(self, mock_format, mock_get):
        # Make sure we just pass through the template URL if the base
        # URLs are not set, i.e. we don't try to format the URL to a template.
        url = 'foo'
        self.flags(transport_url=None)
        self.flags(connection=None, group='database')
        db_mapping = get_db_mapping(transport_url=url,
                                    database_connection=url)
        mock_get.return_value = db_mapping
        mapping_obj = objects.CellMapping().get_by_uuid(self.context,
                db_mapping['uuid'])
        self.assertEqual(url, mapping_obj.database_connection)
        self.assertEqual(url, mapping_obj.transport_url)
        mock_format.assert_not_called()


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

    def test_get_by_disabled(self):
        for ident in (4, 3):
            # We start with id's 4 and 3 because we already have 2 enabled cell
            # mappings in the base test case setup. 4 is before 3 to simply
            # verify the sorting mechanism.
            cm = objects.CellMapping(context=self.context,
                                     id=ident,
                                     uuid=getattr(uuids, 'cell%i' % ident),
                                     transport_url='fake://%i' % ident,
                                     database_connection='fake://%i' % ident,
                                     disabled=True)
            cm.create()
        obj = objects.CellMappingList.get_all(self.context)
        ids = [c.id for c in obj]
        # Returns all the cells
        self.assertEqual([1, 2, 3, 4], ids)

        obj = objects.CellMappingList.get_by_disabled(self.context,
                                                      disabled=False)
        ids = [c.id for c in obj]
        # Returns only the enabled ones
        self.assertEqual([1, 2], ids)

        obj = objects.CellMappingList.get_by_disabled(self.context,
                                                      disabled=True)
        ids = [c.id for c in obj]
        # Returns only the disabled ones
        self.assertEqual([3, 4], ids)


class TestCellMappingListObject(test_objects._LocalTest,
                                _TestCellMappingListObject):
    pass


class TestRemoteCellMappingListObject(test_objects._RemoteTest,
                                      _TestCellMappingListObject):
    pass
