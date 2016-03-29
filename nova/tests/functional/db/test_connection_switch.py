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
from nova.tests import fixtures


class ConnectionSwitchTestCase(test.TestCase):
    test_filename = 'foo.db'
    fake_conn = 'sqlite:///' + test_filename

    def setUp(self):
        super(ConnectionSwitchTestCase, self).setUp()
        self.addCleanup(self.cleanup)
        # Use a file-based sqlite database so data will persist across new
        # connections
        # The 'main' database connection will stay open, so in-memory is fine
        self.useFixture(fixtures.Database(connection=self.fake_conn))

    def cleanup(self):
        try:
            os.remove(self.test_filename)
        except OSError:
            pass

    def test_connection_switch(self):
        # Make a request context with a cell mapping
        mapping = objects.CellMapping(database_connection=self.fake_conn)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        # Create an instance in the cell database
        uuid = uuidutils.generate_uuid()
        with context.target_cell(ctxt, mapping):
            # Must set project_id because instance get specifies
            # project_only=True to model_query, which means non-admin
            # users can only read instances for their project
            instance = objects.Instance(context=ctxt, uuid=uuid,
                                        project_id='fake-project')
            instance.create()

            # Verify the instance is found in the cell database
            inst = objects.Instance.get_by_uuid(ctxt, uuid)
            self.assertEqual(uuid, inst.uuid)

        # Verify the instance isn't found in the main database
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid, ctxt, uuid)
