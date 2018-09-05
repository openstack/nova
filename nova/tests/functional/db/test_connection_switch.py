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

import os

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures


class ConnectionSwitchTestCase(test.NoDBTestCase):
    USES_DB_SELF = True
    test_filename = 'foo.db'
    fake_conn = 'sqlite:///' + test_filename

    def setUp(self):
        super(ConnectionSwitchTestCase, self).setUp()
        self.addCleanup(self.cleanup)
        self.useFixture(nova_fixtures.Database(database='api'))
        self.useFixture(nova_fixtures.Database(database='main'))
        # Use a file-based sqlite database so data will persist across new
        # connections
        # The 'main' database connection will stay open, so in-memory is fine
        self.useFixture(nova_fixtures.Database(connection=self.fake_conn))

    def cleanup(self):
        try:
            os.remove(self.test_filename)
        except OSError:
            pass

    def test_connection_switch(self):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        # Make a request context with a cell mapping
        mapping = objects.CellMapping(context=ctxt,
                                      uuid=uuidutils.generate_uuid(),
                                      database_connection=self.fake_conn,
                                      transport_url='none:///')
        mapping.create()
        # Create an instance in the cell database
        uuid = uuidutils.generate_uuid()
        with context.target_cell(ctxt, mapping) as cctxt:
            # Must set project_id because instance get specifies
            # project_only=True to model_query, which means non-admin
            # users can only read instances for their project
            instance = objects.Instance(context=cctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            # Verify the instance is found in the cell database
            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Verify the instance isn't found in the main database
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid, ctxt, uuid)


class CellDatabasesTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(CellDatabasesTestCase, self).setUp()
        self.useFixture(nova_fixtures.Database(database='api'))
        fix = nova_fixtures.CellDatabases()
        fix.add_cell_database('cell0')
        fix.add_cell_database('cell1')
        fix.add_cell_database('cell2')
        self.useFixture(fix)

        self.context = context.RequestContext('fake-user', 'fake-project')

    def _create_cell_mappings(self):
        cell0_uuid = objects.CellMapping.CELL0_UUID
        self.mapping0 = objects.CellMapping(context=self.context,
                                            uuid=cell0_uuid,
                                            database_connection='cell0',
                                            transport_url='none:///')
        self.mapping1 = objects.CellMapping(context=self.context,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='cell1',
                                            transport_url='none:///')
        self.mapping2 = objects.CellMapping(context=self.context,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='cell2',
                                            transport_url='none:///')
        self.mapping0.create()
        self.mapping1.create()
        self.mapping2.create()

    def test_cell_dbs(self):
        self._create_cell_mappings()

        # Create an instance and read it from cell1
        uuid = uuidutils.generate_uuid()
        with context.target_cell(self.context, self.mapping1) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Make sure it can't be read from cell2
        with context.target_cell(self.context, self.mapping2) as cctxt:
            self.assertRaises(exception.InstanceNotFound,
                              objects.Instance.get_by_uuid, cctxt, uuid)

        # Make sure it can still be read from cell1
        with context.target_cell(self.context, self.mapping1) as cctxt:
            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Create an instance and read it from cell2
        uuid = uuidutils.generate_uuid()
        with context.target_cell(self.context, self.mapping2) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Make sure it can't be read from cell1
        with context.target_cell(self.context, self.mapping1) as cctxt:
            self.assertRaises(exception.InstanceNotFound,
                              objects.Instance.get_by_uuid, cctxt, uuid)

    def test_scatter_gather_cells(self):
        self._create_cell_mappings()

        # Create an instance in cell0
        with context.target_cell(self.context, self.mapping0) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuids.instance0,
                                        project_id='fake-project')
            instance.create()

        # Create an instance in first cell
        with context.target_cell(self.context, self.mapping1) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuids.instance1,
                                        project_id='fake-project')
            instance.create()

        # Create an instance in second cell
        with context.target_cell(self.context, self.mapping2) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuids.instance2,
                                        project_id='fake-project')
            instance.create()

        filters = {'deleted': False, 'project_id': 'fake-project'}
        results = context.scatter_gather_all_cells(
            self.context, objects.InstanceList.get_by_filters, filters,
            sort_dir='asc')
        instances = objects.InstanceList()
        for result in results.values():
            instances = instances + result

        # Should have 3 instances across cells
        self.assertEqual(3, len(instances))

        # Verify we skip cell0 when specified
        results = context.scatter_gather_skip_cell0(
            self.context, objects.InstanceList.get_by_filters, filters)
        instances = objects.InstanceList()
        for result in results.values():
            instances = instances + result

        # Should have gotten only the instances from the last two cells
        self.assertEqual(2, len(instances))
        self.assertIn(self.mapping1.uuid, results)
        self.assertIn(self.mapping2.uuid, results)
        instance_uuids = [inst.uuid for inst in instances]
        self.assertIn(uuids.instance1, instance_uuids)
        self.assertIn(uuids.instance2, instance_uuids)

        # Try passing one cell
        results = context.scatter_gather_cells(
            self.context, [self.mapping1], 60,
            objects.InstanceList.get_by_filters, filters)
        instances = objects.InstanceList()
        for result in results.values():
            instances = instances + result

        # Should have gotten only one instance from cell1
        self.assertEqual(1, len(instances))
        self.assertIn(self.mapping1.uuid, results)
        self.assertEqual(uuids.instance1, instances[0].uuid)
