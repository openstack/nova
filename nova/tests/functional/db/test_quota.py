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
from nova import objects
from nova import quota
from nova import test
from nova.tests import fixtures as nova_fixtures


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

    def test_server_group_members_count_by_user(self):
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
        group.create()
        instance_uuids = []

        # Create an instance in cell1
        with context.target_cell(ctxt, mapping1) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user')
            instance.create()
            instance_uuids.append(instance.uuid)

        # Create an instance in cell2
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user')
            instance.create()
            instance_uuids.append(instance.uuid)

        # Add the uuids to the group
        objects.InstanceGroup.add_members(ctxt, group.uuid, instance_uuids)
        # add_members() doesn't add the members to the object field
        group.members.extend(instance_uuids)

        # Count server group members across cells
        count = quota._server_group_count_members_by_user(ctxt, group,
                                                          'fake-user')

        self.assertEqual(2, count['user']['server_group_members'])

    def test_instances_cores_ram_count(self):
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

        # Create an instance in cell2
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='fake-user',
                                        vcpus=4, memory_mb=1024)
            instance.create()

        # Create an instance in cell2 for a different user
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt,
                                        project_id='fake-project',
                                        user_id='other-fake-user',
                                        vcpus=4, memory_mb=1024)
            instance.create()

        # Count instances, cores, and ram across cells
        count = quota._instances_cores_ram_count(ctxt, 'fake-project',
                                                 user_id='fake-user')

        self.assertEqual(3, count['project']['instances'])
        self.assertEqual(10, count['project']['cores'])
        self.assertEqual(2560, count['project']['ram'])
        self.assertEqual(2, count['user']['instances'])
        self.assertEqual(6, count['user']['cores'])
        self.assertEqual(1536, count['user']['ram'])
