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

import mock
import webob

from nova.api.openstack.compute import server_migrations
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


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


class ServerMigrationsPolicyEnforcementV21(test.NoDBTestCase):
    wsgi_api_version = '2.22'

    def setUp(self):
        super(ServerMigrationsPolicyEnforcementV21, self).setUp()
        self.controller = server_migrations.ServerMigrationsController()
        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)

    def test_migrate_live_policy_failed(self):
        rule_name = "os_compute_api:servers:migrations:force_complete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body_args = {'force_complete': None}
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._force_complete, self.req,
                                fakes.FAKE_UUID, fakes.FAKE_UUID,
                                body=body_args)
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())
