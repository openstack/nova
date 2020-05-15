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

import ddt
import mock
from oslo_utils import uuidutils

from nova import context
from nova import objects
from nova import quota
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.db import test_instance_mapping


@ddt.ddt
class QuotaTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(QuotaTestCase, self).setUp()
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())
        self.useFixture(nova_fixtures.Database(database='api'))
        fix = nova_fixtures.CellDatabases()
        fix.add_cell_database('cell1')
        fix.add_cell_database('cell2')
        self.useFixture(fix)

    @ddt.data(True, False)
    @mock.patch('nova.quota.LOG.warning')
    @mock.patch('nova.quota._user_id_queued_for_delete_populated')
    def test_server_group_members_count_by_user(self, uid_qfd_populated,
                                                mock_uid_qfd_populated,
                                                mock_warn_log):
        mock_uid_qfd_populated.return_value = uid_qfd_populated
        ctxt = context.RequestContext('fake-user', 'fake-project')
        mapping1 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='cell1',
                                       transport_url='none:///')
        mapping2 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='cell2',
                                       transport_url='none:///')
        mapping1.create()
        mapping2.create()

        # Create a server group the instances will use.
        group = objects.InstanceGroup(context=ctxt)
        group.project_id = ctxt.project_id
        group.user_id = ctxt.user_id
        group.create()
        instance_uuids = []

        # Create an instance in cell1
        with context.target_cell(ctxt, mapping1) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user')
            instance.create()
            instance_uuids.append(instance.uuid)
        im = objects.InstanceMapping(context=ctxt,
                                     instance_uuid=instance.uuid,
                                     project_id='fake-project',
                                     user_id='fake-user',
                                     cell_id=mapping1.id)
        im.create()

        # Create an instance in cell2
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user')
            instance.create()
            instance_uuids.append(instance.uuid)
        im = objects.InstanceMapping(context=ctxt,
                                     instance_uuid=instance.uuid,
                                     project_id='fake-project',
                                     user_id='fake-user',
                                     cell_id=mapping2.id)
        im.create()

        # Create an instance that is queued for delete in cell2. It should not
        # be counted
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user')
            instance.create()
            instance.destroy()
            instance_uuids.append(instance.uuid)
        im = objects.InstanceMapping(context=ctxt,
                                     instance_uuid=instance.uuid,
                                     project_id='fake-project',
                                     user_id='fake-user',
                                     cell_id=mapping2.id,
                                     queued_for_delete=True)
        im.create()

        # Add the uuids to the group
        objects.InstanceGroup.add_members(ctxt, group.uuid, instance_uuids)
        # add_members() doesn't add the members to the object field
        group.members.extend(instance_uuids)

        # Count server group members from instance mappings or cell databases,
        # depending on whether the user_id/queued_for_delete data migration has
        # been completed.
        count = quota._server_group_count_members_by_user(ctxt, group,
                                                          'fake-user')

        self.assertEqual(2, count['user']['server_group_members'])

        if uid_qfd_populated:
            # Did not log a warning about falling back to legacy count.
            mock_warn_log.assert_not_called()
        else:
            # Logged a warning about falling back to legacy count.
            mock_warn_log.assert_called_once()

        # Create a duplicate of the cell1 instance in cell2 except hidden.
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user',
                                        uuid=instance_uuids[0],
                                        hidden=True)
            instance.create()
        # The duplicate hidden instance should not be counted.
        count = quota._server_group_count_members_by_user(
            ctxt, group, instance.user_id)
        self.assertEqual(2, count['user']['server_group_members'])

    @mock.patch('nova.objects.CellMappingList.get_by_project_id',
        wraps=objects.CellMappingList.get_by_project_id)
    def test_instances_cores_ram_count(self, mock_get_project_cell_mappings):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        mapping1 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='cell1',
                                       transport_url='none:///')
        mapping2 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='cell2',
                                       transport_url='none:///')
        mapping1.create()
        mapping2.create()

        # Create an instance in cell1
        with context.target_cell(ctxt, mapping1) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user',
                                        vcpus=2, memory_mb=512)
            instance.create()
            # create mapping for the instance since we query only those cells
            # in which the project has instances based on the instance_mappings
            im = objects.InstanceMapping(context=ctxt,
                                         instance_uuid=instance.uuid,
                                         cell_mapping=mapping1,
                                         project_id='fake-project')
            im.create()

        # Create an instance in cell2
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user',
                                        vcpus=4, memory_mb=1024)
            instance.create()
            # create mapping for the instance since we query only those cells
            # in which the project has instances based on the instance_mappings
            im = objects.InstanceMapping(context=ctxt,
                                         instance_uuid=instance.uuid,
                                         cell_mapping=mapping2,
                                         project_id='fake-project')
            im.create()

        # Create an instance in cell2 for a different user
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='other-fake-user',
                                        vcpus=4, memory_mb=1024)
            instance.create()
            # create mapping for the instance since we query only those cells
            # in which the project has instances based on the instance_mappings
            im = objects.InstanceMapping(context=ctxt,
                                         instance_uuid=instance.uuid,
                                         cell_mapping=mapping2,
                                         project_id='fake-project')
            im.create()

        # Count instances, cores, and ram across cells (all cells)
        count = quota._instances_cores_ram_count(ctxt, 'fake-project',
                                                 user_id='fake-user')
        mock_get_project_cell_mappings.assert_not_called()
        self.assertEqual(3, count['project']['instances'])
        self.assertEqual(10, count['project']['cores'])
        self.assertEqual(2560, count['project']['ram'])
        self.assertEqual(2, count['user']['instances'])
        self.assertEqual(6, count['user']['cores'])
        self.assertEqual(1536, count['user']['ram'])

        # Count instances, cores, and ram across cells (query cell subset)
        self.flags(instance_list_per_project_cells=True, group='api')
        count = quota._instances_cores_ram_count(ctxt, 'fake-project',
                                                 user_id='fake-user')
        mock_get_project_cell_mappings.assert_called_with(ctxt, 'fake-project')
        self.assertEqual(3, count['project']['instances'])
        self.assertEqual(10, count['project']['cores'])
        self.assertEqual(2560, count['project']['ram'])
        self.assertEqual(2, count['user']['instances'])
        self.assertEqual(6, count['user']['cores'])
        self.assertEqual(1536, count['user']['ram'])

    def test_user_id_queued_for_delete_populated(self):
        ctxt = context.RequestContext(
            test_instance_mapping.sample_mapping['user_id'],
            test_instance_mapping.sample_mapping['project_id'])

        # One deleted or SOFT_DELETED instance with user_id=None, should not be
        # considered by the check.
        test_instance_mapping.create_mapping(user_id=None,
                                             queued_for_delete=True)

        # Should be True because deleted instances are not considered.
        self.assertTrue(quota._user_id_queued_for_delete_populated(ctxt))

        # A non-deleted instance with user_id=None, should be considered in the
        # check.
        test_instance_mapping.create_mapping(user_id=None,
                                             queued_for_delete=False)

        # Should be False because it's not deleted and user_id is unmigrated.
        self.assertFalse(quota._user_id_queued_for_delete_populated(ctxt))

        # A non-deleted instance in a different project, should be considered
        # in the check (if project_id is not passed).
        test_instance_mapping.create_mapping(queued_for_delete=False,
                                             project_id='other-project')

        # Should be False since only instance 3 has user_id set and we're not
        # filtering on project.
        self.assertFalse(quota._user_id_queued_for_delete_populated(ctxt))

        # Should be True because only instance 3 will be considered when we
        # filter on project.
        self.assertTrue(
            quota._user_id_queued_for_delete_populated(
                ctxt, project_id='other-project'))

        # Add a mapping for an instance that has not yet migrated
        # queued_for_delete.
        test_instance_mapping.create_mapping(queued_for_delete=None)

        # Should be False because an unmigrated queued_for_delete was found.
        self.assertFalse(
            quota._user_id_queued_for_delete_populated(ctxt))

        # Check again filtering on project. Should be True because the
        # unmigrated queued_for_delete record is part of a different project.
        self.assertTrue(
            quota._user_id_queued_for_delete_populated(
                ctxt, project_id='other-project'))
