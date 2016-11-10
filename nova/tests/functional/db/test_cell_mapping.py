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

from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova.objects import cell_mapping
from nova import test
from nova.tests import fixtures


SAMPLE_MAPPING = {'uuid': '',
                  'name': 'fake-cell',
                  'transport_url': 'rabbit:///',
                  'database_connection': 'mysql+pymysql:///'}


def create_mapping(**kwargs):
    args = SAMPLE_MAPPING.copy()
    if 'uuid' not in kwargs:
        args['uuid'] = uuidutils.generate_uuid()
    args.update(kwargs)
    ctxt = context.RequestContext()
    return cell_mapping.CellMapping._create_in_db(ctxt, args)


class CellMappingTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(CellMappingTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.mapping_obj = cell_mapping.CellMapping()

    def test_get_by_uuid(self):
        mapping = create_mapping()
        db_mapping = self.mapping_obj._get_by_uuid_from_db(self.context,
                mapping['uuid'])
        for key in self.mapping_obj.fields.keys():
            self.assertEqual(db_mapping[key], mapping[key])

    def test_get_by_uuid_not_found(self):
        self.assertRaises(exception.CellMappingNotFound,
                self.mapping_obj._get_by_uuid_from_db, self.context,
                          uuidutils.generate_uuid())

    def test_save_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._save_in_db(self.context, mapping['uuid'],
                {'name': 'meow'})
        db_mapping = self.mapping_obj._get_by_uuid_from_db(self.context,
                mapping['uuid'])
        self.assertNotEqual(db_mapping['name'], mapping['name'])
        for key in [key for key in self.mapping_obj.fields.keys()
                    if key not in ['name', 'updated_at']]:
            self.assertEqual(db_mapping[key], mapping[key])

    def test_destroy_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._get_by_uuid_from_db(self.context, mapping['uuid'])
        self.mapping_obj._destroy_in_db(self.context, mapping['uuid'])
        self.assertRaises(exception.CellMappingNotFound,
                self.mapping_obj._get_by_uuid_from_db, self.context,
                mapping['uuid'])

    def test_destroy_in_db_not_found(self):
        self.assertRaises(exception.CellMappingNotFound,
                self.mapping_obj._destroy_in_db, self.context,
                uuidutils.generate_uuid())


class CellMappingListTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(CellMappingListTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))

    def test_get_all(self):
        mappings = {}
        mapping = create_mapping()
        mappings[mapping['uuid']] = mapping
        mapping = create_mapping()
        mappings[mapping['uuid']] = mapping

        ctxt = context.RequestContext()
        db_mappings = cell_mapping.CellMappingList._get_all_from_db(ctxt)
        for db_mapping in db_mappings:
            mapping = mappings[db_mapping.uuid]
            for key in cell_mapping.CellMapping.fields.keys():
                self.assertEqual(db_mapping[key], mapping[key])
