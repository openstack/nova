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

import mock
from oslo_utils import uuidutils
import six
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import migrate_server as \
    migrate_server_v21
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids


class MigrateServerTestsV21(admin_only_action_common.CommonTests):
    migrate_server = migrate_server_v21
    controller_name = 'MigrateServerController'
    validation_error = exception.ValidationError
    _api_version = '2.1'
    disk_over_commit = False
    force = None
    async = False
    host_name = None

    def setUp(self):
        super(MigrateServerTestsV21, self).setUp()
        self.controller = getattr(self.migrate_server, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.migrate_server, self.controller_name,
                       _fake_controller)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _get_migration_body(self, **kwargs):
        return {'os-migrateLive': self._get_params(**kwargs)}

    def _get_params(self, **kwargs):
        return {'host': kwargs.get('host'),
                 'block_migration': kwargs.get('block_migration') or False,
                 'disk_over_commit': self.disk_over_commit}

    def test_migrate(self):
        method_translations = {'_migrate': 'resize',
                               '_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': self._get_migration_body(host='hostname')}
        args_map = {'_migrate_live': ((False, self.disk_over_commit,
                                       'hostname', self.force, self.async),
                                      {}),
                    '_migrate': ((), {'host_name': self.host_name})}
        self._test_actions(['_migrate', '_migrate_live'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_migrate_none_hostname(self):
        method_translations = {'_migrate': 'resize',
                               '_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': self._get_migration_body(host=None)}
        args_map = {'_migrate_live': ((False, self.disk_over_commit, None,
                                       self.force, self.async),
                                      {}),
                    '_migrate': ((), {'host_name': None})}
        self._test_actions(['_migrate', '_migrate_live'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_migrate_with_non_existed_instance(self):
        body_map = {'_migrate_live':
                    self._get_migration_body(host='hostname')}
        self._test_actions_with_non_existed_instance(
            ['_migrate', '_migrate_live'], body_map=body_map)

    def test_migrate_raise_conflict_on_invalid_state(self):
        method_translations = {'_migrate': 'resize',
                               '_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live':
                    self._get_migration_body(host='hostname')}
        args_map = {'_migrate_live': ((False, self.disk_over_commit,
                                       'hostname', self.force, self.async),
                                      {}),
                    '_migrate': ((), {'host_name': self.host_name})}
        exception_arg = {'_migrate': 'migrate',
                         '_migrate_live': 'os-migrateLive'}
        self._test_actions_raise_conflict_on_invalid_state(
            ['_migrate', '_migrate_live'], body_map=body_map,
            args_map=args_map, method_translations=method_translations,
            exception_args=exception_arg)

    def test_actions_with_locked_instance(self):
        method_translations = {'_migrate': 'resize',
                               '_migrate_live': 'live_migrate'}

        body_map = {'_migrate_live':
                    self._get_migration_body(host='hostname')}
        args_map = {'_migrate_live': ((False, self.disk_over_commit,
                                       'hostname', self.force, self.async),
                                      {}),
                    '_migrate': ((), {'host_name': self.host_name})}
        self._test_actions_with_locked_instance(
            ['_migrate', '_migrate_live'], body_map=body_map,
            args_map=args_map, method_translations=method_translations)

    def _test_migrate_exception(self, exc_info, expected_result):
        self.mox.StubOutWithMock(self.compute_api, 'resize')
        instance = self._stub_instance_get()
        self.compute_api.resize(
            self.context, instance,
            host_name=self.host_name).AndRaise(exc_info)

        self.mox.ReplayAll()
        self.assertRaises(expected_result,
                          self.controller._migrate,
                          self.req, instance['uuid'], body={'migrate': None})

    def test_migrate_too_many_instances(self):
        exc_info = exception.TooManyInstances(overs='', req='', used=0,
                                              allowed=0)
        self._test_migrate_exception(exc_info, webob.exc.HTTPForbidden)

    def _test_migrate_live_succeeded(self, param):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')
        instance = self._stub_instance_get()
        self.compute_api.live_migrate(self.context, instance, False,
                                      self.disk_over_commit, 'hostname',
                                      self.force, self.async)

        self.mox.ReplayAll()
        live_migrate_method = self.controller._migrate_live
        live_migrate_method(self.req, instance.uuid,
                            body={'os-migrateLive': param})
        self.assertEqual(202, live_migrate_method.wsgi_code)

    def test_migrate_live_enabled(self):
        param = self._get_params(host='hostname')
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_enabled_with_string_param(self):
        param = {'host': 'hostname',
                 'block_migration': "False",
                 'disk_over_commit': "False"}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_without_host(self):
        body = self._get_migration_body()
        del body['os-migrateLive']['host']
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_without_block_migration(self):
        body = self._get_migration_body()
        del body['os-migrateLive']['block_migration']
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_without_disk_over_commit(self):
        body = {'os-migrateLive':
                {'host': 'hostname',
                 'block_migration': False}}
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_with_invalid_block_migration(self):
        body = self._get_migration_body(block_migration='foo')
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_with_invalid_disk_over_commit(self):
        body = {'os-migrateLive':
                {'host': 'hostname',
                 'block_migration': False,
                 'disk_over_commit': "foo"}}
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_missing_dict_param(self):
        body = self._get_migration_body(host='hostname')
        del body['os-migrateLive']['host']
        body['os-migrateLive']['dummy'] = 'hostname'
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def _test_migrate_live_failed_with_exception(
                                         self, fake_exc,
                                         uuid=None,
                                         expected_exc=webob.exc.HTTPBadRequest,
                                         check_response=True):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')

        instance = self._stub_instance_get(uuid=uuid)
        self.compute_api.live_migrate(self.context, instance, False,
                                      self.disk_over_commit,
                                      'hostname', self.force, self.async
                                      ).AndRaise(fake_exc)
        self.mox.ReplayAll()

        body = self._get_migration_body(host='hostname')
        ex = self.assertRaises(expected_exc,
                               self.controller._migrate_live,
                               self.req, instance.uuid, body=body)
        if check_response:
            self.assertIn(six.text_type(fake_exc), ex.explanation)

    def test_migrate_live_compute_service_unavailable(self):
        self._test_migrate_live_failed_with_exception(
            exception.ComputeServiceUnavailable(host='host'))

    def test_migrate_live_compute_service_not_found(self):
        self._test_migrate_live_failed_with_exception(
            exception.ComputeHostNotFound(host='host'))

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

    def test_migrate_live_instance_not_active(self):
        self._test_migrate_live_failed_with_exception(
            exception.InstanceInvalidState(
                instance_uuid='', state='', attr='', method=''),
            expected_exc=webob.exc.HTTPConflict,
            check_response=False)

    def test_migrate_live_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_migrate_live_migration_precheck_client_exception(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckClientException(reason=''),
            expected_exc=webob.exc.HTTPInternalServerError,
            check_response=False)

    def test_migrate_live_migration_with_unexpected_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationError(reason=''),
            expected_exc=webob.exc.HTTPInternalServerError,
            check_response=False)


class MigrateServerTestsV225(MigrateServerTestsV21):

    # We don't have disk_over_commit in v2.25
    disk_over_commit = None

    def setUp(self):
        super(MigrateServerTestsV225, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.25')

    def _get_params(self, **kwargs):
        return {'host': kwargs.get('host'),
                 'block_migration': kwargs.get('block_migration') or False}

    def test_migrate_live_enabled_with_string_param(self):
        param = {'host': 'hostname',
                 'block_migration': "False"}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_without_disk_over_commit(self):
        pass

    def test_migrate_live_with_invalid_disk_over_commit(self):
        pass

    def test_live_migrate_block_migration_auto(self):
        method_translations = {'_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': {'os-migrateLive': {'host': 'hostname',
                                      'block_migration': 'auto'}}}
        args_map = {'_migrate_live': ((None, None, 'hostname', self.force,
                                       self.async), {})}
        self._test_actions(['_migrate_live'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_migrate_live_with_disk_over_commit_raise(self):
        body = {'os-migrateLive':
                {'host': 'hostname',
                 'block_migration': 'auto',
                 'disk_over_commit': False}}
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_migrate_live_migration_with_old_nova_not_supported(self):
        self._test_migrate_live_failed_with_exception(
            exception.LiveMigrationWithOldNovaNotSupported())


class MigrateServerTestsV230(MigrateServerTestsV225):
    force = False

    def setUp(self):
        super(MigrateServerTestsV230, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.30')

    def _test_live_migrate(self, force=False):
        if force is True:
            litteral_force = 'true'
        else:
            litteral_force = 'false'
        method_translations = {'_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': {'os-migrateLive': {'host': 'hostname',
                                      'block_migration': 'auto',
                                      'force': litteral_force}}}
        args_map = {'_migrate_live': ((None, None, 'hostname', force,
                                       self.async), {})}
        self._test_actions(['_migrate_live'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    def test_live_migrate(self):
        self._test_live_migrate()

    def test_live_migrate_with_forced_host(self):
        self._test_live_migrate(force=True)

    def test_forced_live_migrate_with_no_provided_host(self):
        body = {'os-migrateLive':
                {'force': 'true'}}
        self.assertRaises(self.validation_error,
                          self.controller._migrate_live,
                          self.req, fakes.FAKE_UUID, body=body)


class MigrateServerTestsV234(MigrateServerTestsV230):
    async = True

    def setUp(self):
        super(MigrateServerTestsV234, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.34')

    # NOTE(tdurakov): for REST API version 2.34 and above, tests below are not
    # valid, as they are made in background.
    def test_migrate_live_compute_service_unavailable(self):
        pass

    def test_migrate_live_compute_service_not_found(self):
        pass

    def test_migrate_live_invalid_hypervisor_type(self):
        pass

    def test_migrate_live_invalid_cpu_info(self):
        pass

    def test_migrate_live_unable_to_migrate_to_self(self):
        pass

    def test_migrate_live_destination_hypervisor_too_old(self):
        pass

    def test_migrate_live_no_valid_host(self):
        pass

    def test_migrate_live_invalid_local_storage(self):
        pass

    def test_migrate_live_invalid_shared_storage(self):
        pass

    def test_migrate_live_hypervisor_unavailable(self):
        pass

    def test_migrate_live_instance_not_active(self):
        pass

    def test_migrate_live_pre_check_error(self):
        pass

    def test_migrate_live_migration_precheck_client_exception(self):
        pass

    def test_migrate_live_migration_with_unexpected_error(self):
        pass

    def test_migrate_live_migration_with_old_nova_not_supported(self):
        pass

    def test_migrate_live_unexpected_error(self):
        exc = exception.NoValidHost(reason="No valid host found")
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')
        instance = self._stub_instance_get()
        self.compute_api.live_migrate(self.context, instance, None,
                                      self.disk_over_commit, 'hostname',
                                      self.force, self.async).AndRaise(exc)

        self.mox.ReplayAll()
        body = {'os-migrateLive':
                {'host': 'hostname', 'block_migration': 'auto'}}

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller._migrate_live,
                          self.req, instance.uuid, body=body)


class MigrateServerTestsV256(MigrateServerTestsV234):
    host_name = 'fake-host'
    method_translations = {'_migrate': 'resize'}
    body_map = {'_migrate': {'migrate': {'host': host_name}}}
    args_map = {'_migrate': ((), {'host_name': host_name})}

    def setUp(self):
        super(MigrateServerTestsV256, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.56')

    def _test_migrate_validation_error(self, body):
        self.assertRaises(self.validation_error,
                          self.controller._migrate,
                          self.req, fakes.FAKE_UUID, body=body)

    def _test_migrate_exception(self, exc_info, expected_result):
        @mock.patch.object(self.compute_api, 'get')
        @mock.patch.object(self.compute_api, 'resize', side_effect=exc_info)
        def _test(mock_resize, mock_get):
            instance = objects.Instance(uuid=uuids.instance)
            self.assertRaises(expected_result,
                              self.controller._migrate,
                              self.req, instance['uuid'],
                              body={'migrate': {'host': self.host_name}})
        _test()

    def test_migrate(self):
        self._test_actions(['_migrate'], body_map=self.body_map,
                           method_translations=self.method_translations,
                           args_map=self.args_map)

    def test_migrate_without_host(self):
        # The request body is: '{"migrate": null}'
        body_map = {'_migrate': {'migrate': None}}
        args_map = {'_migrate': ((), {'host_name': None})}
        self._test_actions(['_migrate'], body_map=body_map,
                           method_translations=self.method_translations,
                           args_map=args_map)

    def test_migrate_none_hostname(self):
        # The request body is: '{"migrate": {"host": null}}'
        body_map = {'_migrate': {'migrate': {'host': None}}}
        args_map = {'_migrate': ((), {'host_name': None})}
        self._test_actions(['_migrate'], body_map=body_map,
                           method_translations=self.method_translations,
                           args_map=args_map)

    def test_migrate_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(
            ['_migrate'], body_map=self.body_map)

    def test_migrate_raise_conflict_on_invalid_state(self):
        exception_arg = {'_migrate': 'migrate'}
        self._test_actions_raise_conflict_on_invalid_state(
            ['_migrate'], body_map=self.body_map,
            args_map=self.args_map,
            method_translations=self.method_translations,
            exception_args=exception_arg)

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(
            ['_migrate'], body_map=self.body_map,
            args_map=self.args_map,
            method_translations=self.method_translations)

    def test_migrate_without_migrate_object(self):
        self._test_migrate_validation_error({})

    def test_migrate_invalid_migrate_object(self):
        self._test_migrate_validation_error({'migrate': 'fake-host'})

    def test_migrate_with_additional_property(self):
        self._test_migrate_validation_error(
            {'migrate': {'host': self.host_name,
                         'additional': 'foo'}})

    def test_migrate_with_host_length_more_than_255(self):
        self._test_migrate_validation_error(
            {'migrate': {'host': 'a' * 256}})

    def test_migrate_nonexistent_host(self):
        exc_info = exception.ComputeHostNotFound(host='nonexistent_host')
        self._test_migrate_exception(exc_info, webob.exc.HTTPBadRequest)

    def test_migrate_no_request_spec(self):
        exc_info = exception.CannotMigrateWithTargetHost()
        self._test_migrate_exception(exc_info, webob.exc.HTTPConflict)

    def test_migrate_to_same_host(self):
        exc_info = exception.CannotMigrateToSameHost()
        self._test_migrate_exception(exc_info, webob.exc.HTTPBadRequest)


class MigrateServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(MigrateServerPolicyEnforcementV21, self).setUp()
        self.controller = migrate_server_v21.MigrateServerController()
        self.req = fakes.HTTPRequest.blank('')

    def test_migrate_policy_failed(self):
        rule_name = "os_compute_api:os-migrate-server:migrate"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._migrate, self.req,
                                fakes.FAKE_UUID,
                                body={'migrate': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    def test_migrate_live_policy_failed(self):
        rule_name = "os_compute_api:os-migrate-server:migrate_live"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body_args = {'os-migrateLive': {'host': 'hostname',
                'block_migration': False,
                'disk_over_commit': False}}
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._migrate_live, self.req,
                                fakes.FAKE_UUID,
                                body=body_args)
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())
