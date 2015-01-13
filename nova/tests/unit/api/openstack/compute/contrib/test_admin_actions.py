#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import webob

from nova.api.openstack.compute.contrib import admin_actions as \
    admin_actions_v2
from nova.api.openstack.compute.plugins.v3 import admin_actions as \
    admin_actions_v21
from nova.compute import vm_states
import nova.context
from nova import exception
from nova import objects
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class AdminActionsTestV21(admin_only_action_common.CommonTests):
    admin_actions = admin_actions_v21
    fake_url = '/v2/fake'

    def setUp(self):
        super(AdminActionsTestV21, self).setUp()
        self.controller = self.admin_actions.AdminActionsController()
        self.compute_api = self.controller.compute_api
        self.context = nova.context.RequestContext('fake', 'fake')

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.admin_actions, 'AdminActionsController',
                       _fake_controller)

        self.app = self._get_app()
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('servers',
                                             'os-admin-actions'),
                                  fake_auth_context=self.context)

    def test_actions(self):
        actions = ['resetNetwork', 'injectNetworkInfo']
        method_translations = {'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        self._test_actions(actions, method_translations)

    def test_actions_with_non_existed_instance(self):
        actions = ['resetNetwork', 'injectNetworkInfo', 'os-resetState']
        body_map = {'os-resetState': {'state': 'active'}}

        self._test_actions_with_non_existed_instance(actions,
                                                     body_map=body_map)

    def test_actions_with_locked_instance(self):
        actions = ['resetNetwork', 'injectNetworkInfo']
        method_translations = {'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        self._test_actions_with_locked_instance(actions,
            method_translations=method_translations)


class AdminActionsTestV2(AdminActionsTestV21):
    admin_actions = admin_actions_v2

    def setUp(self):
        super(AdminActionsTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Admin_actions'])

    def _get_app(self):
        return fakes.wsgi_app(init_only=('servers',),
                              fake_auth_context=self.context)

    def test_actions(self):
        actions = ['migrate', 'resetNetwork', 'injectNetworkInfo']
        method_translations = {'migrate': 'resize',
                               'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        self._test_actions(actions, method_translations)

    def test_actions_raise_conflict_on_invalid_state(self):
        actions = ['migrate', 'os-migrateLive']
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive':
                        {'host': 'hostname',
                         'block_migration': False,
                         'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}

        self._test_actions_raise_conflict_on_invalid_state(actions,
            method_translations=method_translations,
            body_map=body_map,
            args_map=args_map)

    def test_actions_with_non_existed_instance(self):
        actions = ['resetNetwork', 'injectNetworkInfo',
                   'os-resetState', 'migrate', 'os-migrateLive']
        body_map = {'os-resetState': {'state': 'active'},
                    'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}}

        self._test_actions_with_non_existed_instance(actions,
                                                     body_map=body_map)

    def test_actions_with_locked_instance(self):
        actions = ['migrate', 'resetNetwork', 'injectNetworkInfo',
                   'os-migrateLive']
        method_translations = {'migrate': 'resize',
                               'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info',
                               'os-migrateLive': 'live_migrate'}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}
        body_map = {'os-migrateLive': {'host': 'hostname',
                                       'block_migration': False,
                                       'disk_over_commit': False}}

        self._test_actions_with_locked_instance(actions,
            method_translations=method_translations,
            body_map=body_map,
            args_map=args_map)

    def _test_migrate_exception(self, exc_info, expected_result):
        self.mox.StubOutWithMock(self.compute_api, 'resize')
        instance = self._stub_instance_get()
        self.compute_api.resize(self.context, instance).AndRaise(exc_info)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {'migrate': None})
        self.assertEqual(expected_result, res.status_int)

    def _test_migrate_live_succeeded(self, param):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')
        instance = self._stub_instance_get()
        self.compute_api.live_migrate(self.context, instance, False,
                                      False, 'hostname')

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
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

    def test_migrate_live_missing_dict_param(self):
        body = {'os-migrateLive': {'dummy': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}}
        res = self._make_request('/servers/FAKE/action', body)
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_block_migration(self):
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': "foo",
                                   'disk_over_commit': False}}
        res = self._make_request('/servers/FAKE/action', body)
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_disk_over_commit(self):
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': "foo"}}
        res = self._make_request('/servers/FAKE/action', body)
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

    def test_migrate_live_migration_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_migrate_live_migration_with_old_nova_not_safe(self):
        self._test_migrate_live_failed_with_exception(
            exception.LiveMigrationWithOldNovaNotSafe(server=''))

    def test_migrate_live_migration_with_unexpected_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationError(reason=''),
            expected_status_code=500,
            check_response=False)


class ResetStateTestsV21(test.NoDBTestCase):
    admin_act = admin_actions_v21
    bad_request = exception.ValidationError
    fake_url = '/servers'

    def setUp(self):
        super(ResetStateTestsV21, self).setUp()
        self.uuid = uuidutils.generate_uuid()
        self.admin_api = self.admin_act.AdminActionsController()
        self.compute_api = self.admin_api.compute_api

        url = '%s/%s/action' % (self.fake_url, self.uuid)
        self.request = self._get_request(url)
        self.context = self.request.environ['nova.context']

    def _get_request(self, url):
        return fakes.HTTPRequest.blank(url)

    def test_no_state(self):
        self.assertRaises(self.bad_request,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": None})

    def test_bad_state(self):
        self.assertRaises(self.bad_request,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": {"state": "spam"}})

    def test_no_instance(self):
        self.mox.StubOutWithMock(self.compute_api, 'get')
        exc = exception.InstanceNotFound(instance_id='inst_ud')
        self.compute_api.get(self.context, self.uuid, expected_attrs=None,
                             want_objects=True).AndRaise(exc)
        self.mox.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": {"state": "active"}})

    def _setup_mock(self, expected):
        instance = objects.Instance()
        instance.uuid = self.uuid
        instance.vm_state = 'fake'
        instance.task_state = 'fake'
        instance.obj_reset_changes()

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api, 'get')

        def check_state(admin_state_reset=True):
            self.assertEqual(set(expected.keys()),
                             instance.obj_what_changed())
            for k, v in expected.items():
                self.assertEqual(v, getattr(instance, k),
                                 "Instance.%s doesn't match" % k)
            instance.obj_reset_changes()

        self.compute_api.get(self.context, instance.uuid, expected_attrs=None,
                             want_objects=True).AndReturn(instance)
        instance.save(admin_state_reset=True).WithSideEffects(check_state)

    def test_reset_active(self):
        self._setup_mock(dict(vm_state=vm_states.ACTIVE,
                              task_state=None))
        self.mox.ReplayAll()

        body = {"os-resetState": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, self.uuid,
                                             body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.admin_api,
                      admin_actions_v21.AdminActionsController):
            status_int = self.admin_api._reset_state.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

    def test_reset_error(self):
        self._setup_mock(dict(vm_state=vm_states.ERROR,
                              task_state=None))
        self.mox.ReplayAll()
        body = {"os-resetState": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, self.uuid,
                                             body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.admin_api,
                      admin_actions_v21.AdminActionsController):
            status_int = self.admin_api._reset_state.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)


class ResetStateTestsV2(ResetStateTestsV21):
    admin_act = admin_actions_v2
    bad_request = webob.exc.HTTPBadRequest
    fake_url = '/fake/servers'
