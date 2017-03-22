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

import mock

from nova.api.openstack.compute import migrations as migrations_v21
from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids


fake_migrations = [
    # in-progress live migration
    {
        'id': 1,
        'source_node': 'node1',
        'dest_node': 'node2',
        'source_compute': 'compute1',
        'dest_compute': 'compute2',
        'dest_host': '1.2.3.4',
        'status': 'running',
        'instance_uuid': uuids.instance1,
        'old_instance_type_id': 1,
        'new_instance_type_id': 2,
        'migration_type': 'live-migration',
        'hidden': False,
        'memory_total': 123456,
        'memory_processed': 12345,
        'memory_remaining': 111111,
        'disk_total': 234567,
        'disk_processed': 23456,
        'disk_remaining': 211111,
        'created_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'deleted_at': None,
        'deleted': False
    },
    # non in-progress live migration
    {
        'id': 2,
        'source_node': 'node1',
        'dest_node': 'node2',
        'source_compute': 'compute1',
        'dest_compute': 'compute2',
        'dest_host': '1.2.3.4',
        'status': 'error',
        'instance_uuid': uuids.instance1,
        'old_instance_type_id': 1,
        'new_instance_type_id': 2,
        'migration_type': 'live-migration',
        'hidden': False,
        'memory_total': 123456,
        'memory_processed': 12345,
        'memory_remaining': 111111,
        'disk_total': 234567,
        'disk_processed': 23456,
        'disk_remaining': 211111,
        'created_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
        'deleted_at': None,
        'deleted': False
    },
    # in-progress resize
    {
        'id': 4,
        'source_node': 'node10',
        'dest_node': 'node20',
        'source_compute': 'compute10',
        'dest_compute': 'compute20',
        'dest_host': '5.6.7.8',
        'status': 'migrating',
        'instance_uuid': uuids.instance2,
        'old_instance_type_id': 5,
        'new_instance_type_id': 6,
        'migration_type': 'resize',
        'hidden': False,
        'memory_total': 456789,
        'memory_processed': 56789,
        'memory_remaining': 45000,
        'disk_total': 96789,
        'disk_processed': 6789,
        'disk_remaining': 96000,
        'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'deleted_at': None,
        'deleted': False
    },
    # non in-progress resize
    {
        'id': 5,
        'source_node': 'node10',
        'dest_node': 'node20',
        'source_compute': 'compute10',
        'dest_compute': 'compute20',
        'dest_host': '5.6.7.8',
        'status': 'error',
        'instance_uuid': uuids.instance2,
        'old_instance_type_id': 5,
        'new_instance_type_id': 6,
        'migration_type': 'resize',
        'hidden': False,
        'memory_total': 456789,
        'memory_processed': 56789,
        'memory_remaining': 45000,
        'disk_total': 96789,
        'disk_processed': 6789,
        'disk_remaining': 96000,
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
    environ = {"nova.context": context.RequestContext('fake_user', 'fake',
                                                      is_admin=True)}
    GET = {}


class MigrationsTestCaseV21(test.NoDBTestCase):
    migrations = migrations_v21

    def _migrations_output(self):
        return self.controller._output(self.req, migrations_obj)

    def setUp(self):
        """Run before each test."""
        super(MigrationsTestCaseV21, self).setUp()
        self.controller = self.migrations.MigrationsController()
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.context = self.req.environ['nova.context']

    def test_index(self):
        migrations_in_progress = {'migrations': self._migrations_output()}

        for mig in migrations_in_progress['migrations']:
            self.assertIn('id', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)
            self.assertNotIn('links', mig)

        filters = {'host': 'host1', 'status': 'migrating',
                   'cell_name': 'ChildCell'}
        self.req.GET.update(filters)

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations',
                               return_value=migrations_obj) as (
            mock_get_migrations
        ):
            response = self.controller.index(self.req)
            self.assertEqual(migrations_in_progress, response)
            mock_get_migrations.assert_called_once_with(self.context, filters)


class MigrationsTestCaseV223(MigrationsTestCaseV21):
    wsgi_api_version = '2.23'

    def setUp(self):
        """Run before each test."""
        super(MigrationsTestCaseV223, self).setUp()
        self.req = fakes.HTTPRequest.blank(
            '', version=self.wsgi_api_version, use_admin_context=True)

    def test_index(self):
        migrations = {'migrations': self.controller._output(
                                        self.req, migrations_obj, True)}

        for i, mig in enumerate(migrations['migrations']):
            # first item is in-progress live migration
            if i == 0:
                self.assertIn('links', mig)
            else:
                self.assertNotIn('links', mig)

            self.assertIn('migration_type', mig)
            self.assertIn('id', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations') as m_get:
            m_get.return_value = migrations_obj
            response = self.controller.index(self.req)
            self.assertEqual(migrations, response)
            self.assertIn('links', response['migrations'][0])
            self.assertIn('migration_type', response['migrations'][0])


class MigrationsPolicyEnforcement(test.NoDBTestCase):
    def setUp(self):
        super(MigrationsPolicyEnforcement, self).setUp()
        self.controller = migrations_v21.MigrationsController()
        self.req = fakes.HTTPRequest.blank('')

    def test_list_policy_failed(self):
        rule_name = "os_compute_api:os-migrations:index"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class MigrationsPolicyEnforcementV223(MigrationsPolicyEnforcement):
    wsgi_api_version = '2.23'

    def setUp(self):
        super(MigrationsPolicyEnforcementV223, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)
