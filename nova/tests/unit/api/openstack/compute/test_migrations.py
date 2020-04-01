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

import iso8601
import mock
from oslo_utils.fixture import uuidsentinel as uuids
import six
from webob import exc

from nova.api.openstack.compute import migrations as migrations_v21
from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova import test
from nova.tests.unit.api.openstack import fakes


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
        'deleted': False,
        'uuid': uuids.migration1,
        'cross_cell_move': False,
        'user_id': None,
        'project_id': None
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
        'deleted': False,
        'uuid': uuids.migration2,
        'cross_cell_move': False,
        'user_id': None,
        'project_id': None
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
        'deleted': False,
        'uuid': uuids.migration3,
        'cross_cell_move': False,
        'user_id': None,
        'project_id': None
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
        'deleted': False,
        'uuid': uuids.migration4,
        'cross_cell_move': False,
        'user_id': None,
        'project_id': None
    }
]

migrations_obj = base.obj_make_list(
    'fake-context',
    objects.MigrationList(),
    objects.Migration,
    fake_migrations)


class FakeRequest(object):
    environ = {"nova.context": context.RequestContext('fake_user',
                                                      fakes.FAKE_PROJECT_ID,
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
                   'instance_uuid': uuids.instance1,
                   'source_compute': 'host1', 'hidden': '0',
                   'migration_type': 'resize'}

        # python-novaclient actually supports sending this even though it's
        # not used in the DB API layer and is totally useless. This lets us,
        # however, test that additionalProperties=True allows it.
        unknown_filter = {'cell_name': 'ChildCell'}

        self.req.GET.update(filters)
        self.req.GET.update(unknown_filter)

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations',
                               return_value=migrations_obj) as (
            mock_get_migrations
        ):
            response = self.controller.index(self.req)
            self.assertEqual(migrations_in_progress, response)
            # Only with the filters, and the unknown filter is stripped
            mock_get_migrations.assert_called_once_with(self.context, filters)

    def test_index_query_allow_negative_int_as_string(self):
        migrations = {'migrations': self._migrations_output()}
        filters = ['host', 'status', 'cell_name', 'instance_uuid',
                   'source_compute', 'hidden', 'migration_type']

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations',
                               return_value=migrations_obj):
            for fl in filters:
                req = fakes.HTTPRequest.blank('/os-migrations',
                                              use_admin_context=True,
                                              query_string='%s=-1' % fl)
                response = self.controller.index(req)
                self.assertEqual(migrations, response)

    def test_index_query_duplicate_query_parameters(self):
        migrations = {'migrations': self._migrations_output()}
        params = {'host': 'host1', 'status': 'migrating',
                  'cell_name': 'ChildCell', 'instance_uuid': uuids.instance1,
                  'source_compute': 'host1', 'hidden': '0',
                  'migration_type': 'resize'}

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations',
                               return_value=migrations_obj):
            for k, v in params.items():
                req = fakes.HTTPRequest.blank(
                    '/os-migrations', use_admin_context=True,
                    query_string='%s=%s&%s=%s' % (k, v, k, v))
                response = self.controller.index(req)
                self.assertEqual(migrations, response)


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


class MigrationsTestCaseV259(MigrationsTestCaseV223):
    wsgi_api_version = '2.59'

    def test_index(self):
        migrations = {'migrations': self.controller._output(
                                        self.req, migrations_obj, True, True)}

        for i, mig in enumerate(migrations['migrations']):
            # first item is in-progress live migration
            if i == 0:
                self.assertIn('links', mig)
            else:
                self.assertNotIn('links', mig)

            self.assertIn('migration_type', mig)
            self.assertIn('id', mig)
            self.assertIn('uuid', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations_sorted') as m_get:
            m_get.return_value = migrations_obj
            response = self.controller.index(self.req)
            self.assertEqual(migrations, response)
            self.assertIn('links', response['migrations'][0])
            self.assertIn('migration_type', response['migrations'][0])

    @mock.patch('nova.compute.api.API.get_migrations_sorted')
    def test_index_with_invalid_marker(self, mock_migrations_get):
        """Tests detail paging with an invalid marker (not found)."""
        mock_migrations_get.side_effect = exception.MarkerNotFound(
            marker=uuids.invalid_marker)
        req = fakes.HTTPRequest.blank(
            '/os-migrations?marker=%s' % uuids.invalid_marker,
            version=self.wsgi_api_version, use_admin_context=True)
        e = self.assertRaises(exc.HTTPBadRequest,
                              self.controller.index, req)
        self.assertEqual(
            "Marker %s could not be found." % uuids.invalid_marker,
            six.text_type(e))

    def test_index_with_invalid_limit(self):
        """Tests detail paging with an invalid limit."""
        req = fakes.HTTPRequest.blank(
            '/os-migrations?limit=x', version=self.wsgi_api_version,
            use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)
        req = fakes.HTTPRequest.blank(
            '/os-migrations?limit=-1', version=self.wsgi_api_version,
            use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_with_invalid_changes_since(self):
        """Tests detail paging with an invalid changes-since value."""
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-since=wrong_time',
            version=self.wsgi_api_version, use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_with_unknown_query_param(self):
        """Tests detail paging with an unknown query parameter."""
        req = fakes.HTTPRequest.blank(
            '/os-migrations?foo=bar',
            version=self.wsgi_api_version, use_admin_context=True)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    @mock.patch('nova.compute.api.API.get_migrations',
                return_value=objects.MigrationList())
    def test_index_with_changes_since_old_microversion(self, get_migrations):
        """Tests that the changes-since query parameter is ignored before
        microversion 2.59.
        """
        # Also use a valid filter (instance_uuid) to make sure only
        # changes-since is removed.
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-since=2018-01-10T16:59:24.138939&'
            'instance_uuid=%s' % uuids.instance_uuid,
            version='2.58', use_admin_context=True)
        result = self.controller.index(req)
        self.assertEqual({'migrations': []}, result)
        get_migrations.assert_called_once_with(
            req.environ['nova.context'],
            {'instance_uuid': uuids.instance_uuid})


class MigrationTestCaseV266(MigrationsTestCaseV259):
    wsgi_api_version = '2.66'

    def test_index_with_invalid_changes_before(self):
        """Tests detail paging with an invalid changes-before value."""
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-before=wrong_time',
            version=self.wsgi_api_version, use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    @mock.patch('nova.compute.api.API.get_migrations_sorted',
                return_value=objects.MigrationList())
    def test_index_with_changes_since_and_changes_before(
            self, get_migrations_sorted):
        changes_since = '2013-10-22T13:42:02Z'
        changes_before = '2013-10-22T13:42:03Z'
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-since=%s&changes-before=%s&'
            'instance_uuid=%s'
            % (changes_since, changes_before, uuids.instance_uuid),
            version=self.wsgi_api_version,
            use_admin_context=True)

        self.controller.index(req)
        search_opts = {'instance_uuid': uuids.instance_uuid,
                       'changes-before':
                           datetime.datetime(2013, 10, 22, 13, 42, 3,
                                             tzinfo=iso8601.iso8601.UTC),
                       'changes-since':
                           datetime.datetime(2013, 10, 22, 13, 42, 2,
                                             tzinfo=iso8601.iso8601.UTC)}
        get_migrations_sorted.assert_called_once_with(
            req.environ['nova.context'], search_opts, sort_dirs=mock.ANY,
            sort_keys=mock.ANY, limit=1000, marker=None)

    def test_get_migrations_filters_with_distinct_changes_time_bad_request(
            self):
        changes_since = '2018-09-04T05:45:27Z'
        changes_before = '2018-09-03T05:45:27Z'
        req = fakes.HTTPRequest.blank('/os-migrations?'
                                      'changes-since=%s&changes-before=%s' %
                                      (changes_since, changes_before),
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        ex = self.assertRaises(exc.HTTPBadRequest, self.controller.index, req)
        self.assertIn('The value of changes-since must be less than '
                      'or equal to changes-before', six.text_type(ex))

    def test_index_with_changes_before_old_microversion_failed(self):
        """Tests that the changes-before query parameter is an error before
        microversion 2.66.
        """
        # Also use a valid filter (instance_uuid) to make sure
        # changes-before is an additional property.
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-before=2018-01-10T16:59:24.138939&'
            'instance_uuid=%s' % uuids.instance_uuid,
            version='2.65', use_admin_context=True)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    @mock.patch('nova.compute.api.API.get_migrations',
                return_value=objects.MigrationList())
    def test_index_with_changes_before_old_microversion(self, get_migrations):
        """Tests that the changes-before query parameter is ignored before
        microversion 2.59.
        """
        # Also use a valid filter (instance_uuid) to make sure only
        # changes-before is removed.
        req = fakes.HTTPRequest.blank(
            '/os-migrations?changes-before=2018-01-10T16:59:24.138939&'
            'instance_uuid=%s' % uuids.instance_uuid,
            version='2.58', use_admin_context=True)
        result = self.controller.index(req)
        self.assertEqual({'migrations': []}, result)
        get_migrations.assert_called_once_with(
            req.environ['nova.context'],
            {'instance_uuid': uuids.instance_uuid})


class MigrationsTestCaseV280(MigrationTestCaseV266):
    wsgi_api_version = '2.80'

    def test_index(self):
        migrations = {'migrations': self.controller._output(
                                        self.req, migrations_obj,
                                        add_link=True, add_uuid=True,
                                        add_user_project=True)}

        for i, mig in enumerate(migrations['migrations']):
            # first item is in-progress live migration
            if i == 0:
                self.assertIn('links', mig)
            else:
                self.assertNotIn('links', mig)

            self.assertIn('migration_type', mig)
            self.assertIn('id', mig)
            self.assertIn('uuid', mig)
            self.assertIn('user_id', mig)
            self.assertIn('project_id', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)

        with mock.patch.object(self.controller.compute_api,
                               'get_migrations_sorted') as m_get:
            m_get.return_value = migrations_obj
            response = self.controller.index(self.req)
            self.assertEqual(migrations, response)
            self.assertIn('links', response['migrations'][0])
            self.assertIn('migration_type', response['migrations'][0])

    def test_index_filter_by_user_id_pre_v280(self):
        """Tests that the migrations by user_id query parameter
        is not allowed before microversion 2.80.
        """
        req = fakes.HTTPRequest.blank(
            '/os-migrations?user_id=%s' % uuids.user_id,
            version='2.79', use_admin_context=True)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    def test_index_filter_by_project_id_pre_v280(self):
        """Tests that the migrations by project_id query parameter
        is not allowed before microversion 2.80.
        """
        req = fakes.HTTPRequest.blank(
            '/os-migrations?project_id=%s' % uuids.project_id,
            version='2.79', use_admin_context=True)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))
