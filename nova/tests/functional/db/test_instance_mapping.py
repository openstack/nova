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
from oslo_utils.fixture import uuidsentinel
from oslo_utils import uuidutils

from nova.compute import vm_states
from nova import context
from nova import exception
from nova.objects import cell_mapping
from nova.objects import instance
from nova.objects import instance_mapping
from nova.objects import virtual_interface
from nova import test
from nova.tests import fixtures


sample_mapping = {'instance_uuid': '',
                  'cell_id': 3,
                  'project_id': 'fake-project',
                  'user_id': 'fake-user'}


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

        # Run it again to make sure we don't query the cell database for
        # instances if we didn't get any un-migrated mappings.
        with mock.patch('nova.objects.InstanceList.get_by_filters',
                        new_callable=mock.NonCallableMock):
            done, total = instance_mapping.populate_queued_for_delete(
                self.context, 1000)
        self.assertEqual(0, done)
        self.assertEqual(0, total)

    def test_user_id_not_set_if_null_from_db(self):
        # Create an instance mapping with user_id=None.
        db_mapping = create_mapping(user_id=None)
        self.assertIsNone(db_mapping['user_id'])
        # Get the mapping to run convert from db object to versioned object.
        im = instance_mapping.InstanceMapping.get_by_instance_uuid(
            self.context, db_mapping['instance_uuid'])
        # Verify the user_id is not set.
        self.assertNotIn('user_id', im)

    @mock.patch('nova.objects.instance_mapping.LOG.warning')
    def test_populate_user_id(self, mock_log_warning):
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

        # Create 5 instances per cell
        for cell in cells:
            for i in range(0, 5):
                with context.target_cell(self.context, cell) as cctxt:
                    inst = instance.Instance(
                        cctxt,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id)
                    inst.create()
                # Make every other mapping have a NULL user_id
                # Will be a total of four mappings with NULL user_id
                user_id = self.context.user_id if i % 2 == 0 else None
                create_mapping(project_id=self.context.project_id,
                               user_id=user_id, cell_id=cell.id,
                               instance_uuid=inst.uuid)

        # Create a SOFT_DELETED instance with a user_id=None instance mapping.
        # This should get migrated.
        with context.target_cell(self.context, cells[0]) as cctxt:
            inst = instance.Instance(
                cctxt, project_id=self.context.project_id,
                user_id=self.context.user_id, vm_state=vm_states.SOFT_DELETED)
            inst.create()
        create_mapping(project_id=self.context.project_id, user_id=None,
                       cell_id=cells[0].id, instance_uuid=inst.uuid,
                       queued_for_delete=True)

        # Create a deleted instance with a user_id=None instance mapping.
        # This should get migrated.
        with context.target_cell(self.context, cells[1]) as cctxt:
            inst = instance.Instance(
                cctxt, project_id=self.context.project_id,
                user_id=self.context.user_id)
            inst.create()
            inst.destroy()
        create_mapping(project_id=self.context.project_id, user_id=None,
                       cell_id=cells[1].id, instance_uuid=inst.uuid,
                       queued_for_delete=True)

        # Create an instance mapping for an instance not yet scheduled. It
        # should not get migrated because we won't know what user_id to use.
        unscheduled = create_mapping(project_id=self.context.project_id,
                                     user_id=None, cell_id=None)

        # Create two instance mappings for instances that no longer exist.
        # Example: residue from a manual cleanup or after a periodic compute
        # purge and before a database archive. This record should not get
        # migrated.
        nonexistent = []
        for i in range(2):
            nonexistent.append(
                create_mapping(project_id=self.context.project_id,
                               user_id=None, cell_id=cells[i].id,
                               instance_uuid=uuidutils.generate_uuid()))

        # Create an instance mapping simulating a virtual interface migration
        # marker instance which has had map_instances run on it.
        # This should not be found by the migration.
        create_mapping(project_id=virtual_interface.FAKE_UUID, user_id=None)

        found, done = instance_mapping.populate_user_id(self.context, 2)
        # Two needed fixing, and honored the limit.
        self.assertEqual(2, found)
        self.assertEqual(2, done)

        found, done = instance_mapping.populate_user_id(self.context, 1000)
        # Only four left were fixable. The fifth instance found has no
        # cell and cannot be migrated yet. The 6th and 7th instances found have
        # no corresponding instance records and cannot be migrated.
        self.assertEqual(7, found)
        self.assertEqual(4, done)

        # Verify the orphaned instance mappings warning log message was only
        # emitted once.
        mock_log_warning.assert_called_once()

        # Check that we have only the expected number of records with
        # user_id set. We created 10 instances (5 per cell with 2 per cell
        # with NULL user_id), 1 SOFT_DELETED instance with NULL user_id,
        # 1 deleted instance with NULL user_id, and 1 not-yet-scheduled
        # instance with NULL user_id.
        # We expect 12 of them to have user_id set after migration (15 total,
        # with the not-yet-scheduled instance and the orphaned instance
        # mappings ignored).
        ims = instance_mapping.InstanceMappingList.get_by_project_id(
            self.context, self.context.project_id)
        self.assertEqual(12, len(
            [im for im in ims if 'user_id' in im]))

        # Check that one instance mapping record (not yet scheduled) has not
        # been migrated by this script.
        # Check that two other instance mapping records (no longer existing
        # instances) have not been migrated by this script.
        self.assertEqual(15, len(ims))

        # Set the cell and create the instance for the mapping without a cell,
        # then run the migration again.
        unscheduled = instance_mapping.InstanceMapping.get_by_instance_uuid(
            self.context, unscheduled['instance_uuid'])
        unscheduled.cell_mapping = cells[0]
        unscheduled.save()
        with context.target_cell(self.context, cells[0]) as cctxt:
            inst = instance.Instance(
                cctxt,
                uuid=unscheduled.instance_uuid,
                project_id=self.context.project_id,
                user_id=self.context.user_id)
            inst.create()
        found, done = instance_mapping.populate_user_id(self.context, 1000)
        # Should have found the not-yet-scheduled instance and the orphaned
        # instance mappings.
        self.assertEqual(3, found)
        # Should have only migrated the not-yet-schedule instance.
        self.assertEqual(1, done)

        # Delete the orphaned instance mapping (simulate manual cleanup by an
        # operator).
        for db_im in nonexistent:
            nonexist = instance_mapping.InstanceMapping.get_by_instance_uuid(
                self.context, db_im['instance_uuid'])
            nonexist.destroy()

        # Run the script one last time to make sure it finds nothing left to
        # migrate.
        found, done = instance_mapping.populate_user_id(self.context, 1000)
        self.assertEqual(0, found)
        self.assertEqual(0, done)

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    def test_populate_user_id_instance_get_fail(self, mock_inst_get):
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

        # Create one instance per cell
        for cell in cells:
            with context.target_cell(self.context, cell) as cctxt:
                inst = instance.Instance(
                    cctxt,
                    project_id=self.context.project_id,
                    user_id=self.context.user_id)
                inst.create()
            create_mapping(project_id=self.context.project_id,
                           user_id=None, cell_id=cell.id,
                           instance_uuid=inst.uuid)

        # Simulate the first cell is down/has some error
        mock_inst_get.side_effect = [test.TestingException(),
                                     instance.InstanceList(objects=[inst])]

        found, done = instance_mapping.populate_user_id(self.context, 1000)
        # Verify we continue to the next cell when a down/error cell is
        # encountered.
        self.assertEqual(2, found)
        self.assertEqual(1, done)


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

    def test_get_not_deleted_by_cell_and_project(self):
        cells = []
        # Create two cells
        for uuid in (uuidsentinel.cell1, uuidsentinel.cell2):
            cm = cell_mapping.CellMapping(context=self.context, uuid=uuid,
                                          database_connection="fake:///",
                                          transport_url='fake://')
            cm.create()
            cells.append(cm)

        uuids = {cells[0]: [uuidsentinel.c1i1, uuidsentinel.c1i2],
                 cells[1]: [uuidsentinel.c2i1, uuidsentinel.c2i2]}
        project_ids = ['fake-project-1', 'fake-project-2']
        # Create five instance_mappings such that:
        for cell, uuid in uuids.items():
            # Both the cells contain a mapping belonging to fake-project-1
            im1 = instance_mapping.InstanceMapping(context=self.context,
                project_id=project_ids[0], cell_mapping=cell,
                instance_uuid=uuid[0], queued_for_delete=False)
            im1.create()
            # Both the cells contain a mapping belonging to fake-project-2
            im2 = instance_mapping.InstanceMapping(context=self.context,
                project_id=project_ids[1], cell_mapping=cell,
                instance_uuid=uuid[1], queued_for_delete=False)
            im2.create()
            # The second cell has a third mapping that is queued for deletion
            # which belongs to fake-project-1.
            if cell.uuid == uuidsentinel.cell2:
                im3 = instance_mapping.InstanceMapping(context=self.context,
                    project_id=project_ids[0], cell_mapping=cell,
                    instance_uuid=uuidsentinel.qfd, queued_for_delete=True)
                im3.create()

        # Get not queued for deletion mappings from cell1 belonging to
        # fake-project-2.
        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(
               self.context, cells[0].uuid, 'fake-project-2'))
        # This will give us one mapping from cell1
        self.assertEqual([uuidsentinel.c1i2],
                         sorted([m.instance_uuid for m in ims]))
        self.assertIn('cell_mapping', ims[0])
        # Get not queued for deletion mappings from cell2 belonging to
        # fake-project-1.
        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(
               self.context, cells[1].uuid, 'fake-project-1'))
        # This will give us one mapping from cell2. Note that even if
        # there are two mappings belonging to fake-project-1 inside cell2,
        # only the one not queued for deletion is returned.
        self.assertEqual([uuidsentinel.c2i1],
                         sorted([m.instance_uuid for m in ims]))
        # Try getting a mapping belonging to a non-existing project_id.
        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(
               self.context, cells[0].uuid, 'fake-project-3'))
        # Since no mappings belong to fake-project-3, nothing is returned.
        self.assertEqual([], sorted([m.instance_uuid for m in ims]))

    def test_get_not_deleted_by_cell_and_project_limit(self):
        cm = cell_mapping.CellMapping(context=self.context,
                                      uuid=uuidsentinel.cell,
                                      database_connection='fake:///',
                                      transport_url='fake://')
        cm.create()
        pid = self.context.project_id
        for uuid in (uuidsentinel.uuid2, uuidsentinel.inst2):
            im = instance_mapping.InstanceMapping(context=self.context,
                                                  project_id=pid,
                                                  cell_mapping=cm,
                                                  instance_uuid=uuid,
                                                  queued_for_delete=False)
            im.create()

        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(self.context,
                                                   cm.uuid,
                                                   pid))
        self.assertEqual(2, len(ims))

        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(self.context,
                                                   cm.uuid,
                                                   pid,
                                                   limit=10))
        self.assertEqual(2, len(ims))

        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(self.context,
                                                   cm.uuid,
                                                   pid,
                                                   limit=1))
        self.assertEqual(1, len(ims))

    def test_get_not_deleted_by_cell_and_project_None(self):
        cm = cell_mapping.CellMapping(context=self.context,
                                      uuid=uuidsentinel.cell,
                                      database_connection='fake:///',
                                      transport_url='fake://')
        cm.create()
        im1 = instance_mapping.InstanceMapping(context=self.context,
                                               project_id='fake-project-1',
                                               cell_mapping=cm,
                                               instance_uuid=uuidsentinel.uid1,
                                               queued_for_delete=False)
        im1.create()
        im2 = instance_mapping.InstanceMapping(context=self.context,
                                               project_id='fake-project-2',
                                               cell_mapping=cm,
                                               instance_uuid=uuidsentinel.uid2,
                                               queued_for_delete=None)
        im2.create()
        # testing if it accepts None project_id in the query and
        # catches None queued for delete records.
        ims = (instance_mapping.InstanceMappingList.
               get_not_deleted_by_cell_and_project(self.context,
                                                   cm.uuid,
                                                   None))
        self.assertEqual(2, len(ims))

    def test_get_counts(self):
        create_mapping(project_id='fake-project', user_id='fake-user',
                       queued_for_delete=False)
        # mapping with another user
        create_mapping(project_id='fake-project', user_id='other-user',
                       queued_for_delete=False)
        # mapping in another project
        create_mapping(project_id='other-project', user_id='fake-user',
                       queued_for_delete=False)
        # queued_for_delete=True, should not be counted
        create_mapping(project_id='fake-project', user_id='fake-user',
                       queued_for_delete=True)
        # queued_for_delete=None (not yet migrated), should not be counted
        create_mapping(project_id='fake-project', user_id='fake-user',
                       queued_for_delete=None)

        # Count only across a project
        counts = instance_mapping.InstanceMappingList.get_counts(
            self.context, 'fake-project')
        self.assertEqual(2, counts['project']['instances'])
        self.assertNotIn('user', counts)

        # Count across a project and a user
        counts = instance_mapping.InstanceMappingList.get_counts(
            self.context, 'fake-project', user_id='fake-user')
        self.assertEqual(2, counts['project']['instances'])
        self.assertEqual(1, counts['user']['instances'])
