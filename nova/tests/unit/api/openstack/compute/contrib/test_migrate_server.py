# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from nova.api.openstack.compute.plugins.v3 import migrate_server
from nova import exception
from nova.openstack.common import uuidutils
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class MigrateServerTests(admin_only_action_common.CommonTests):
    def setUp(self):
        super(MigrateServerTests, self).setUp()
        self.controller = migrate_server.MigrateServerController()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(migrate_server, 'MigrateServerController',
                       _fake_controller)
        self.app = fakes.wsgi_app_v21(init_only=('servers',
                                                 'os-migrate-server'),
                                      fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_migrate(self):
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive': {'host': 'hostname',
                                       'block_migration': False,
                                       'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}
        self._test_actions(['migrate', 'os-migrateLive'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_migrate_none_hostname(self):
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive': {'host': None,
                                       'block_migration': False,
                                       'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, None), {})}
        self._test_actions(['migrate', 'os-migrateLive'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_migrate_with_non_existed_instance(self):
        body_map = {'os-migrateLive': {'host': 'hostname',
                                     'block_migration': False,
                                     'disk_over_commit': False}}
        self._test_actions_with_non_existed_instance(
            ['migrate', 'os-migrateLive'], body_map=body_map)

    def test_migrate_raise_conflict_on_invalid_state(self):
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive': {'host': 'hostname',
                                       'block_migration': False,
                                       'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}
        self._test_actions_raise_conflict_on_invalid_state(
            ['migrate', 'os-migrateLive'], body_map=body_map,
            args_map=args_map, method_translations=method_translations)

    def test_actions_with_locked_instance(self):
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive': {'host': 'hostname',
                                       'block_migration': False,
                                       'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}
        self._test_actions_with_locked_instance(
            ['migrate', 'os-migrateLive'], body_map=body_map,
            args_map=args_map, method_translations=method_translations)

    def _test_migrate_exception(self, exc_info, expected_result):
        self.mox.StubOutWithMock(self.compute_api, 'resize')
        instance = self._stub_instance_get()
        self.compute_api.resize(self.context, instance).AndRaise(exc_info)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {'migrate': None})
        self.assertEqual(expected_result, res.status_int)

    def test_migrate_too_many_instances(self):
        exc_info = exception.TooManyInstances(overs='', req='', used=0,
                                              allowed=0, resource='')
        self._test_migrate_exception(exc_info, 403)

    def _test_migrate_live_succeeded(self, param):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')
        instance = self._stub_instance_get()
        self.compute_api.live_migrate(self.context, instance, False,
                                      False, 'hostname')

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {'os-migrateLive': param})
        self.assertEqual(202, res.status_int)

    def test_migrate_live_enabled(self):
        param = {'host': 'hostname',
                 'block_migration': False,
                 'disk_over_commit': False}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_enabled_with_string_param(self):
        param = {'host': 'hostname',
                 'block_migration': "False",
                 'disk_over_commit': "False"}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_without_host(self):
        res = self._make_request('/servers/FAKE/action',
                                 {'os-migrateLive':
                                  {'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(400, res.status_int)

    def test_migrate_live_without_block_migration(self):
        res = self._make_request('/servers/FAKE/action',
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'disk_over_commit': False}})
        self.assertEqual(400, res.status_int)

    def test_migrate_live_without_disk_over_commit(self):
        res = self._make_request('/servers/FAKE/action',
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False}})
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_block_migration(self):
        res = self._make_request('/servers/FAKE/action',
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': "foo",
                                   'disk_over_commit': False}})
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_disk_over_commit(self):
        res = self._make_request('/servers/FAKE/action',
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': "foo"}})
        self.assertEqual(400, res.status_int)

    def _test_migrate_live_failed_with_exception(self, fake_exc,
                                                 uuid=None,
                                                 expected_status_code=400,
                                                 check_response=True):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')

        instance = self._stub_instance_get(uuid=uuid)
        self.compute_api.live_migrate(self.context, instance, False,
                                      False, 'hostname').AndRaise(fake_exc)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(expected_status_code, res.status_int)
        if check_response:
            self.assertIn(unicode(fake_exc), res.body)

    def test_migrate_live_compute_service_unavailable(self):
        self._test_migrate_live_failed_with_exception(
            exception.ComputeServiceUnavailable(host='host'))

    def test_migrate_live_invalid_hypervisor_type(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidHypervisorType())

    def test_migrate_live_invalid_cpu_info(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidCPUInfo(reason=""))

    def test_migrate_live_unable_to_migrate_to_self(self):
        uuid = uuidutils.generate_uuid()
        self._test_migrate_live_failed_with_exception(
                exception.UnableToMigrateToSelf(instance_id=uuid,
                                                host='host'),
                                                uuid=uuid)

    def test_migrate_live_destination_hypervisor_too_old(self):
        self._test_migrate_live_failed_with_exception(
            exception.DestinationHypervisorTooOld())

    def test_migrate_live_no_valid_host(self):
        self._test_migrate_live_failed_with_exception(
            exception.NoValidHost(reason=''))

    def test_migrate_live_invalid_local_storage(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidLocalStorage(path='', reason=''))

    def test_migrate_live_invalid_shared_storage(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidSharedStorage(path='', reason=''))

    def test_migrate_live_hypervisor_unavailable(self):
        self._test_migrate_live_failed_with_exception(
            exception.HypervisorUnavailable(host=""))

    def test_migrate_live_instance_not_running(self):
        self._test_migrate_live_failed_with_exception(
            exception.InstanceNotRunning(instance_id=""))

    def test_migrate_live_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_migrate_live_migration_with_old_nova_not_safe(self):
        self._test_migrate_live_failed_with_exception(
            exception.LiveMigrationWithOldNovaNotSafe(server=''))

    def test_migrate_live_migration_with_unexpected_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationError(reason=''), expected_status_code=500,
            check_response=False)
