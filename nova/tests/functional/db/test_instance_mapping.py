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
from nova.objects import instance_mapping
from nova import test
from nova.tests import fixtures


sample_mapping = {'instance_uuid': '',
                  'cell_id': 3,
                  'project_id': 'fake-project'}


def create_mapping(**kwargs):
    args = sample_mapping.copy()
    if 'instance_uuid' not in kwargs:
        args['instance_uuid'] = uuidutils.generate_uuid()
    args.update(kwargs)
    ctxt = context.RequestContext('fake-user', 'fake-project')
    return instance_mapping.InstanceMapping._create_in_db(ctxt, args)


class InstanceMappingTestCase(test.NoDBTestCase):
    def setUp(self):
        super(InstanceMappingTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.mapping_obj = instance_mapping.InstanceMapping()

    def test_get_by_instance_uuid(self):
        mapping = create_mapping()
        db_mapping = self.mapping_obj._get_by_instance_uuid_from_db(
                self.context, mapping['instance_uuid'])
        for key in self.mapping_obj.fields.keys():
            self.assertEqual(db_mapping[key], mapping[key])

    def test_get_by_instance_uuid_not_found(self):
        self.assertRaises(exception.InstanceMappingNotFound,
                self.mapping_obj._get_by_instance_uuid_from_db, self.context,
                uuidutils.generate_uuid())

    def test_save_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._save_in_db(self.context, mapping['instance_uuid'],
                {'cell_id': 42})
        db_mapping = self.mapping_obj._get_by_instance_uuid_from_db(
                self.context, mapping['instance_uuid'])
        self.assertNotEqual(db_mapping['cell_id'], mapping['cell_id'])
        for key in [key for key in self.mapping_obj.fields.keys()
                    if key not in ['cell_id', 'updated_at']]:
            self.assertEqual(db_mapping[key], mapping[key])

    def test_destroy_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._get_by_instance_uuid_from_db(self.context,
                mapping['instance_uuid'])
        self.mapping_obj._destroy_in_db(self.context, mapping['instance_uuid'])
        self.assertRaises(exception.InstanceMappingNotFound,
                self.mapping_obj._get_by_instance_uuid_from_db, self.context,
                mapping['instance_uuid'])


class InstanceMappingListTestCase(test.NoDBTestCase):
    def setUp(self):
        super(InstanceMappingListTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.list_obj = instance_mapping.InstanceMappingList()

    def test_get_by_project_id_from_db(self):
        project_id = 'fake-project'
        mappings = {}
        mapping = create_mapping(project_id=project_id)
        mappings[mapping['instance_uuid']] = mapping
        mapping = create_mapping(project_id=project_id)
        mappings[mapping['instance_uuid']] = mapping

        db_mappings = self.list_obj._get_by_project_id_from_db(
                self.context, project_id)
        for db_mapping in db_mappings:
            mapping = mappings[db_mapping.instance_uuid]
            for key in instance_mapping.InstanceMapping.fields.keys():
                self.assertEqual(db_mapping[key], mapping[key])
