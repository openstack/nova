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
        fix.add_cell_database('blah')
        fix.add_cell_database('wat')
        self.useFixture(fix)

    def test_cell_dbs(self):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        mapping1 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='blah',
                                       transport_url='none:///')
        mapping2 = objects.CellMapping(context=ctxt,
                                       uuid=uuidutils.generate_uuid(),
                                       database_connection='wat',
                                       transport_url='none:///')
        mapping1.create()
        mapping2.create()

        # Create an instance and read it from cell1
        uuid = uuidutils.generate_uuid()
        with context.target_cell(ctxt, mapping1) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Make sure it can't be read from cell2
        with context.target_cell(ctxt, mapping2) as cctxt:
            self.assertRaises(exception.InstanceNotFound,
                              objects.Instance.get_by_uuid, cctxt, uuid)

        # Make sure it can still be read from cell1
        with context.target_cell(ctxt, mapping1) as cctxt:
            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Create an instance and read it from cell2
        uuid = uuidutils.generate_uuid()
        with context.target_cell(ctxt, mapping2) as cctxt:
            instance = objects.Instance(context=cctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            inst = objects.Instance.get_by_uuid(cctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Make sure it can't be read from cell1
        with context.target_cell(ctxt, mapping1) as cctxt:
            self.assertRaises(exception.InstanceNotFound,
                              objects.Instance.get_by_uuid, cctxt, uuid)
