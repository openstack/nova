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

from nova.compute import vm_states
from nova import context
from nova import exception
from nova.objects import cell_mapping
from nova.objects import instance
from nova.objects import instance_mapping
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel


sample_mapping = {'instance_uuid': '',
                  'cell_id': 3,
                  'project_id': 'fake-project'}


sample_cell_mapping = {'id': 3,
                       'uuid': '',
                       'name': 'fake-cell',
                       'transport_url': 'rabbit:///',
                       'database_connection': 'mysql:///'}


def create_cell_mapping(**kwargs):
    args = sample_cell_mapping.copy()
    if 'uuid' not in kwargs:
        args['uuid'] = uuidutils.generate_uuid()
    args.update(kwargs)
    ctxt = context.RequestContext('fake-user', 'fake-project')
    return cell_mapping.CellMapping._create_in_db(ctxt, args)


def create_mapping(**kwargs):
    args = sample_mapping.copy()
    if 'instance_uuid' not in kwargs:
        args['instance_uuid'] = uuidutils.generate_uuid()
    args.update(kwargs)
    ctxt = context.RequestContext('fake-user', 'fake-project')
    return instance_mapping.InstanceMapping._create_in_db(ctxt, args)


class InstanceMappingTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(InstanceMappingTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.mapping_obj = instance_mapping.InstanceMapping()

    def test_get_by_instance_uuid(self):
        cell_mapping = create_cell_mapping()
        mapping = create_mapping()
        db_mapping = self.mapping_obj._get_by_instance_uuid_from_db(
                self.context, mapping['instance_uuid'])
        for key in [key for key in self.mapping_obj.fields.keys()
                    if key != 'cell_mapping']:
            self.assertEqual(db_mapping[key], mapping[key])
        self.assertEqual(db_mapping['cell_mapping']['id'], cell_mapping['id'])

    def test_get_by_instance_uuid_not_found(self):
        self.assertRaises(exception.InstanceMappingNotFound,
                self.mapping_obj._get_by_instance_uuid_from_db, self.context,
                uuidutils.generate_uuid())

    def test_save_in_db(self):
        mapping = create_mapping()
        cell_mapping = create_cell_mapping()
        self.mapping_obj._save_in_db(self.context, mapping['instance_uuid'],
                {'cell_id': cell_mapping['id']})
        db_mapping = self.mapping_obj._get_by_instance_uuid_from_db(
                self.context, mapping['instance_uuid'])
        for key in [key for key in self.mapping_obj.fields.keys()
                    if key not in ['cell_id', 'cell_mapping', 'updated_at']]:
            self.assertEqual(db_mapping[key], mapping[key])
        self.assertEqual(db_mapping['cell_id'], cell_mapping['id'])

    def test_destroy_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._get_by_instance_uuid_from_db(self.context,
                mapping['instance_uuid'])
        self.mapping_obj._destroy_in_db(self.context, mapping['instance_uuid'])
        self.assertRaises(exception.InstanceMappingNotFound,
                self.mapping_obj._get_by_instance_uuid_from_db, self.context,
                mapping['instance_uuid'])

    def test_cell_id_nullable(self):
        # Just ensure this doesn't raise
        create_mapping(cell_id=None)

    def test_modify_cell_mapping(self):
        inst_mapping = instance_mapping.InstanceMapping(context=self.context)
        inst_mapping.instance_uuid = uuidutils.generate_uuid()
        inst_mapping.project_id = self.context.project_id
        inst_mapping.cell_mapping = None
        inst_mapping.create()

        c_mapping = cell_mapping.CellMapping(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name="cell0",
                transport_url="none:///",
                database_connection="fake:///")
        c_mapping.create()

        inst_mapping.cell_mapping = c_mapping
        inst_mapping.save()

        result_mapping = instance_mapping.InstanceMapping.get_by_instance_uuid(
                                    self.context, inst_mapping.instance_uuid)

        self.assertEqual(result_mapping.cell_mapping.id,
                         c_mapping.id)

    def test_populate_queued_for_delete(self):
        cells = []
        celldbs = fixtures.CellDatabases()

        # Create two cell databases and map them
        for uuid in (uuidsentinel.cell1, uuidsentinel.cell2):
            cm = cell_mapping.CellMapping(context=self.context, uuid=uuid,
                                          database_connection=uuid,
                                          transport_url='fake://')
            cm.create()
            cells.append(cm)
            celldbs.add_cell_database(uuid)
        self.useFixture(celldbs)

        # Create 5 instances per cell, two deleted, one with matching
        # queued_for_delete in the instance mapping
        for cell in cells:
            for i in range(0, 5):
                # Instance 4 should be SOFT_DELETED
                vm_state = (vm_states.SOFT_DELETED if i == 4
                            else vm_states.ACTIVE)

                # Instance 2 should already be marked as queued_for_delete
                qfd = True if i == 2 else None

                with context.target_cell(self.context, cell) as cctxt:
                    inst = instance.Instance(
                        cctxt,
                        vm_state=vm_state,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id)
                    inst.create()
                    if i in (2, 3):
                        # Instances 2 and 3 are hard-deleted
                        inst.destroy()

                instance_mapping.InstanceMapping._create_in_db(
                    self.context,
                    {'project_id': self.context.project_id,
                     'cell_id': cell.id,
                     'queued_for_delete': qfd,
                     'instance_uuid': inst.uuid})

        done, total = instance_mapping.populate_queued_for_delete(self.context,
                                                                  2)
        # First two needed fixing, and honored the limit
        self.assertEqual(2, done)
        self.assertEqual(2, total)

        done, total = instance_mapping.populate_queued_for_delete(self.context,
                                                                  1000)

        # Last six included two that were already done, and spanned to the
        # next cell
        self.assertEqual(6, done)
        self.assertEqual(6, total)

        mappings = instance_mapping.InstanceMappingList.get_by_project_id(
            self.context, self.context.project_id)

        # Check that we have only the expected number of records with
        # True/False (which implies no NULL records).

        # Six deleted instances
        self.assertEqual(6, len(
            [im for im in mappings if im.queued_for_delete is True]))
        # Four non-deleted instances
        self.assertEqual(4, len(
            [im for im in mappings if im.queued_for_delete is False]))


class InstanceMappingListTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

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

    def test_instance_mapping_list_get_by_cell_id(self):
        """Tests getting all of the InstanceMappings for a given CellMapping id
        """
        # we shouldn't have any instance mappings yet
        inst_mapping_list = (
            instance_mapping.InstanceMappingList.get_by_cell_id(
                self.context, sample_cell_mapping['id'])
        )
        self.assertEqual(0, len(inst_mapping_list))
        # now create an instance mapping in a cell
        db_inst_mapping1 = create_mapping()
        # let's also create an instance mapping that's not in a cell to make
        # sure our filtering is working
        db_inst_mapping2 = create_mapping(cell_id=None)
        self.assertIsNone(db_inst_mapping2['cell_id'])
        # now we should list out one instance mapping for the cell
        inst_mapping_list = (
            instance_mapping.InstanceMappingList.get_by_cell_id(
                self.context, db_inst_mapping1['cell_id'])
        )
        self.assertEqual(1, len(inst_mapping_list))
        self.assertEqual(db_inst_mapping1['id'], inst_mapping_list[0].id)

    def test_instance_mapping_get_by_instance_uuids(self):
        db_inst_mapping1 = create_mapping()
        db_inst_mapping2 = create_mapping(cell_id=None)
        # Create a third that we won't include
        create_mapping()
        uuids = [db_inst_mapping1.instance_uuid,
                 db_inst_mapping2.instance_uuid]
        mappings = instance_mapping.InstanceMappingList.get_by_instance_uuids(
            self.context, uuids + [uuidsentinel.deleted_instance])
        self.assertEqual(sorted(uuids),
                         sorted([m.instance_uuid for m in mappings]))
