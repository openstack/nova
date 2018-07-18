# Copyright 2016 OpenStack Foundation
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

import copy
import datetime

import mock
import six
import webob

from nova.api.openstack.compute import server_migrations
from nova import exception
from nova import objects
from nova.objects import base
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids

SERVER_UUID = uuids.server_uuid

fake_migrations = [
    {
        'id': 1234,
        'source_node': 'node1',
        'dest_node': 'node2',
        'source_compute': 'compute1',
        'dest_compute': 'compute2',
        'dest_host': '1.2.3.4',
        'status': 'running',
        'instance_uuid': SERVER_UUID,
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
    },
    {
        'id': 5678,
        'source_node': 'node10',
        'dest_node': 'node20',
        'source_compute': 'compute10',
        'dest_compute': 'compute20',
        'dest_host': '5.6.7.8',
        'status': 'running',
        'instance_uuid': SERVER_UUID,
        'old_instance_type_id': 5,
        'new_instance_type_id': 6,
        'migration_type': 'live-migration',
        'hidden': False,
        'memory_total': 456789,
        'memory_processed': 56789,
        'memory_remaining': 400000,
        'disk_total': 96789,
        'disk_processed': 6789,
        'disk_remaining': 90000,
        'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
        'deleted_at': None,
        'deleted': False,
        'uuid': uuids.migration2,
    }
]

migrations_obj = base.obj_make_list(
    'fake-context',
    objects.MigrationList(),
    objects.Migration,
    fake_migrations)


class ServerMigrationsTestsV21(test.NoDBTestCase):
    wsgi_api_version = '2.22'

    def setUp(self):
        super(ServerMigrationsTestsV21, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)
        self.context = self.req.environ['nova.context']
        self.controller = server_migrations.ServerMigrationsController()
        self.compute_api = self.controller.compute_api

    def test_force_complete_succeeded(self):
        @mock.patch.object(self.compute_api, 'live_migrate_force_complete')
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(compute_api_get, live_migrate_force_complete):
            self.controller._force_complete(self.req, '1', '1',
                                            body={'force_complete': None})
            live_migrate_force_complete.assert_called_once_with(
                self.context, compute_api_get(), '1')
        _do_test()

    def _test_force_complete_failed_with_exception(self, fake_exc,
                                                   expected_exc):
        @mock.patch.object(self.compute_api, 'live_migrate_force_complete',
                           side_effect=fake_exc)
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(compute_api_get, live_migrate_force_complete):
            self.assertRaises(expected_exc,
                              self.controller._force_complete,
                              self.req, '1', '1',
                              body={'force_complete': None})
        _do_test()

    def test_force_complete_instance_not_migrating(self):
        self._test_force_complete_failed_with_exception(
            exception.InstanceInvalidState(instance_uuid='', state='',
                                           attr='', method=''),
            webob.exc.HTTPConflict)

    def test_force_complete_migration_not_found(self):
        self._test_force_complete_failed_with_exception(
            exception.MigrationNotFoundByStatus(instance_id='', status=''),
            webob.exc.HTTPBadRequest)

    def test_force_complete_instance_is_locked(self):
        self._test_force_complete_failed_with_exception(
            exception.InstanceIsLocked(instance_uuid=''),
            webob.exc.HTTPConflict)

    def test_force_complete_invalid_migration_state(self):
        self._test_force_complete_failed_with_exception(
            exception.InvalidMigrationState(migration_id='', instance_uuid='',
                                            state='', method=''),
            webob.exc.HTTPBadRequest)

    def test_force_complete_instance_not_found(self):
        self._test_force_complete_failed_with_exception(
            exception.InstanceNotFound(instance_id=''),
            webob.exc.HTTPNotFound)

    def test_force_complete_unexpected_error(self):
            self._test_force_complete_failed_with_exception(
                exception.NovaException(), webob.exc.HTTPInternalServerError)


class ServerMigrationsTestsV223(ServerMigrationsTestsV21):
    wsgi_api_version = '2.23'

    def setUp(self):
        super(ServerMigrationsTestsV223, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version,
                                           use_admin_context=True)
        self.context = self.req.environ['nova.context']

    @mock.patch('nova.compute.api.API.get_migrations_in_progress_by_instance')
    @mock.patch('nova.compute.api.API.get')
    def test_index(self, m_get_instance, m_get_mig):
        migrations = [server_migrations.output(mig) for mig in migrations_obj]
        migrations_in_progress = {'migrations': migrations}

        for mig in migrations_in_progress['migrations']:
            self.assertIn('id', mig)
            self.assertNotIn('deleted', mig)
            self.assertNotIn('deleted_at', mig)

        m_get_mig.return_value = migrations_obj
        response = self.controller.index(self.req, SERVER_UUID)
        self.assertEqual(migrations_in_progress, response)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get')
    def test_index_invalid_instance(self, m_get_instance):
        m_get_instance.side_effect = exception.InstanceNotFound(instance_id=1)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index,
                          self.req, SERVER_UUID)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get_migration_by_id_and_instance')
    @mock.patch('nova.compute.api.API.get')
    def test_show(self, m_get_instance, m_get_mig):
        migrations = [server_migrations.output(mig) for mig in migrations_obj]
        m_get_mig.return_value = migrations_obj[0]
        response = self.controller.show(self.req, SERVER_UUID,
                                        migrations_obj[0].id)
        self.assertEqual(migrations[0], response['migration'])

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get_migration_by_id_and_instance')
    @mock.patch('nova.compute.api.API.get')
    def test_show_migration_non_progress(self, m_get_instance, m_get_mig):
        non_progress_mig = copy.deepcopy(migrations_obj[0])
        non_progress_mig.status = "reverted"
        m_get_mig.return_value = non_progress_mig
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          self.req, SERVER_UUID,
                          non_progress_mig.id)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get_migration_by_id_and_instance')
    @mock.patch('nova.compute.api.API.get')
    def test_show_migration_not_live_migration(self, m_get_instance,
                                               m_get_mig):
        non_progress_mig = copy.deepcopy(migrations_obj[0])
        non_progress_mig.migration_type = "resize"
        m_get_mig.return_value = non_progress_mig
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          self.req, SERVER_UUID,
                          non_progress_mig.id)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get_migration_by_id_and_instance')
    @mock.patch('nova.compute.api.API.get')
    def test_show_migration_not_exist(self, m_get_instance, m_get_mig):
        m_get_mig.side_effect = exception.MigrationNotFoundForInstance(
            migration_id=migrations_obj[0].id,
            instance_id=SERVER_UUID)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          self.req, SERVER_UUID,
                          migrations_obj[0].id)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)

    @mock.patch('nova.compute.api.API.get')
    def test_show_migration_invalid_instance(self, m_get_instance):
        m_get_instance.side_effect = exception.InstanceNotFound(instance_id=1)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          self.req, SERVER_UUID,
                          migrations_obj[0].id)

        m_get_instance.assert_called_once_with(self.context, SERVER_UUID,
                                               expected_attrs=None)


class ServerMigrationsTestsV224(ServerMigrationsTestsV21):
    wsgi_api_version = '2.24'

    def setUp(self):
        super(ServerMigrationsTestsV224, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version,
                                           use_admin_context=True)
        self.context = self.req.environ['nova.context']

    def test_cancel_live_migration_succeeded(self):
        @mock.patch.object(self.compute_api, 'live_migrate_abort')
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(mock_get, mock_abort):
            self.controller.delete(self.req, 'server-id', 'migration-id')
            mock_abort.assert_called_once_with(self.context,
                                               mock_get(),
                                               'migration-id',
                                               support_abort_in_queue=False)
        _do_test()

    def _test_cancel_live_migration_failed(self, fake_exc, expected_exc):
        @mock.patch.object(self.compute_api, 'live_migrate_abort',
                           side_effect=fake_exc)
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(mock_get, mock_abort):
            self.assertRaises(expected_exc,
                              self.controller.delete,
                              self.req,
                              'server-id',
                              'migration-id')
        _do_test()

    def test_cancel_live_migration_invalid_state(self):
        self._test_cancel_live_migration_failed(
                exception.InstanceInvalidState(instance_uuid='',
                                               state='',
                                               attr='',
                                               method=''),
                webob.exc.HTTPConflict)

    def test_cancel_live_migration_migration_not_found(self):
        self._test_cancel_live_migration_failed(
                exception.MigrationNotFoundForInstance(migration_id='',
                                                       instance_id=''),
                webob.exc.HTTPNotFound)

    def test_cancel_live_migration_invalid_migration_state(self):
        self._test_cancel_live_migration_failed(
                exception.InvalidMigrationState(migration_id='',
                                                instance_uuid='',
                                                state='',
                                                method=''),
                webob.exc.HTTPBadRequest)

    def test_cancel_live_migration_instance_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          self.req,
                          'server-id',
                          'migration-id')


class ServerMigrationsTestsV265(ServerMigrationsTestsV224):
    wsgi_api_version = '2.65'

    def test_cancel_live_migration_succeeded(self):
        @mock.patch.object(self.compute_api, 'live_migrate_abort')
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(mock_get, mock_abort):
            self.controller.delete(self.req, 'server-id', 1)
            mock_abort.assert_called_once_with(self.context,
                                               mock_get.return_value, 1,
                                               support_abort_in_queue=True)
        _do_test()

    def test_cancel_live_migration_in_queue_not_yet_available(self):
        exc = exception.AbortQueuedLiveMigrationNotYetSupported(
            migration_id=1, status='queued')

        @mock.patch.object(self.compute_api, 'live_migrate_abort',
                           side_effect=exc)
        @mock.patch.object(self.compute_api, 'get')
        def _do_test(mock_get, mock_abort):
            error = self.assertRaises(webob.exc.HTTPConflict,
                                      self.controller.delete,
                                      self.req, 'server-id', 1)
            self.assertIn("Aborting live migration 1 with status queued is "
                          "not yet supported for this instance.",
                          six.text_type(error))
            mock_abort.assert_called_once_with(self.context,
                                               mock_get.return_value, 1,
                                               support_abort_in_queue=True)
        _do_test()


class ServerMigrationsPolicyEnforcementV21(test.NoDBTestCase):
    wsgi_api_version = '2.22'

    def setUp(self):
        super(ServerMigrationsPolicyEnforcementV21, self).setUp()
        self.controller = server_migrations.ServerMigrationsController()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)

    def test_force_complete_policy_failed(self):
        rule_name = "os_compute_api:servers:migrations:force_complete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body_args = {'force_complete': None}
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._force_complete, self.req,
                                fakes.FAKE_UUID, fakes.FAKE_UUID,
                                body=body_args)
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())


class ServerMigrationsPolicyEnforcementV223(
                ServerMigrationsPolicyEnforcementV21):

    wsgi_api_version = '2.23'

    def test_migration_index_failed(self):
        rule_name = "os_compute_api:servers:migrations:index"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.index, self.req,
                                fakes.FAKE_UUID)
        self.assertEqual("Policy doesn't allow %s to be performed." %
                         rule_name, exc.format_message())

    def test_migration_show_failed(self):
        rule_name = "os_compute_api:servers:migrations:show"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.show, self.req,
                                fakes.FAKE_UUID, 1)
        self.assertEqual("Policy doesn't allow %s to be performed." %
                         rule_name, exc.format_message())


class ServerMigrationsPolicyEnforcementV224(
                ServerMigrationsPolicyEnforcementV223):

    wsgi_api_version = '2.24'

    def test_migrate_delete_failed(self):
        rule_name = "os_compute_api:servers:migrations:delete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete, self.req,
                          fakes.FAKE_UUID, '10')
