# All Rights Reserved.
#
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

import datetime

from oslotest import moxstubout

from nova.api.openstack.compute.contrib import migrations as migrations_v2
from nova.api.openstack.compute.plugins.v3 import migrations as migrations_v21
from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova import test

fake_migrations = [
    {
        'id': 1234,
        'source_node': 'node1',
        'dest_node': 'node2',
        'source_compute': 'compute1',
        'dest_compute': 'compute2',
        'dest_host': '1.2.3.4',
        'status': 'Done',
        'instance_uuid': 'instance_id_123',
        'old_instance_type_id': 1,
        'new_instance_type_id': 2,
        'created_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'deleted_at': None,
        'deleted': False
    },
    {
        'id': 5678,
        'source_node': 'node10',
        'dest_node': 'node20',
        'source_compute': 'compute10',
        'dest_compute': 'compute20',
        'dest_host': '5.6.7.8',
        'status': 'Done',
        'instance_uuid': 'instance_id_456',
        'old_instance_type_id': 5,
        'new_instance_type_id': 6,
        'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'deleted_at': None,
        'deleted': False
    }
]

migrations_obj = base.obj_make_list(
    'fake-context',
    objects.MigrationList(),
    objects.Migration,
    fake_migrations)


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}
    GET = {}


class MigrationsTestCaseV21(test.NoDBTestCase):
    migrations = migrations_v21

    def setUp(self):
        """Run before each test."""
        super(MigrationsTestCaseV21, self).setUp()
        self.controller = self.migrations.MigrationsController()
        self.context = context.get_admin_context()
        self.req = FakeRequest()
        self.req.environ['nova.context'] = self.context
        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox

    def test_index(self):
        migrations_in_progress = {
            'migrations': self.migrations.output(migrations_obj)}

        for mig in migrations_in_progress['migrations']:
            self.assertIn('id', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)

        filters = {'host': 'host1', 'status': 'migrating',
                   'cell_name': 'ChildCell'}
        self.req.GET = filters
        self.mox.StubOutWithMock(self.controller.compute_api,
                                 "get_migrations")

        self.controller.compute_api.get_migrations(
            self.context, filters).AndReturn(migrations_obj)
        self.mox.ReplayAll()

        response = self.controller.index(self.req)
        self.assertEqual(migrations_in_progress, response)

    def test_index_needs_authorization(self):
        user_context = context.RequestContext(user_id=None,
                                              project_id=None,
                                              is_admin=False,
                                              read_deleted="no",
                                              overwrite=False)
        self.req.environ['nova.context'] = user_context

        self.assertRaises(exception.PolicyNotAuthorized, self.controller.index,
                          self.req)


class MigrationsTestCaseV2(MigrationsTestCaseV21):
    migrations = migrations_v2
