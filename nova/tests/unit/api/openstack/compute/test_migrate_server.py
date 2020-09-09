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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import six
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import migrate_server as \
    migrate_server_v21
from nova import exception
from nova import objects
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class MigrateServerTestsV21(admin_only_action_common.CommonTests):
    migrate_server = migrate_server_v21
    controller_name = 'MigrateServerController'
    validation_error = exception.ValidationError
    _api_version = '2.1'
    disk_over_commit = False
    force = None
    async_ = False
    host_name = None

    def setUp(self):
        super(MigrateServerTestsV21, self).setUp()
        self.controller = getattr(self.migrate_server, self.controller_name)()
        self.compute_api = self.controller.compute_api
        self.stub_out('nova.api.openstack.compute.migrate_server.'
                      'MigrateServerController',
                      lambda *a, **kw: self.controller)
        self.mock_list_port = self.useFixture(
            fixtures.MockPatch('nova.network.neutron.API.list_ports')).mock
        self.mock_list_port.return_value = {'ports': []}

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
                                       'hostname', self.force, self.async_),
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
                                       self.force, self.async_),
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
                                       'hostname', self.force, self.async_),
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
                                       'hostname', self.force, self.async_),
                                      {}),
                    '_migrate': ((), {'host_name': self.host_name})}
        self._test_actions_with_locked_instance(
            ['_migrate', '_migrate_live'], body_map=body_map,
            args_map=args_map, method_translations=method_translations)

    def _test_migrate_exception(self, exc_info, expected_result):
        instance = self._stub_instance_get()

        with mock.patch.object(self.compute_api, 'resize',
                               side_effect=exc_info) as mock_resize:
            self.assertRaises(expected_result,
                              self.controller._migrate,
                              self.req, instance['uuid'],
                              body={'migrate': None})
            mock_resize.assert_called_once_with(
                self.context, instance, host_name=self.host_name)
        self.mock_get.assert_called_once_with(
            self.context, instance.uuid, expected_attrs=['flavor', 'services'],
            cell_down_support=False)

    def test_migrate_too_many_instances(self):
        exc_info = exception.TooManyInstances(overs='', req='', used=0,
                                              allowed=0)
        self._test_migrate_exception(exc_info, webob.exc.HTTPForbidden)

    def _test_migrate_live_succeeded(self, param):
        instance = self._stub_instance_get()

        live_migrate_method = self.controller._migrate_live

        with mock.patch.object(self.compute_api,
                               'live_migrate') as mock_live_migrate:
            live_migrate_method(self.req, instance.uuid,
                                body={'os-migrateLive': param})
            self.assertEqual(202, live_migrate_method.wsgi_code)
            mock_live_migrate.assert_called_once_with(
                self.context, instance, False, self.disk_over_commit,
                'hostname', self.force, self.async_)

        self.mock_get.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=['numa_topology'],
                                              cell_down_support=False)

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
        instance = self._stub_instance_get(uuid=uuid)
        body = self._get_migration_body(host='hostname')

        with mock.patch.object(
                self.compute_api, 'live_migrate',
                side_effect=fake_exc) as mock_live_migrate:
            ex = self.assertRaises(expected_exc,
                                   self.controller._migrate_live,
                                   self.req, instance.uuid, body=body)
            if check_response:
                self.assertIn(six.text_type(fake_exc), ex.explanation)
            mock_live_migrate.assert_called_once_with(
                self.context, instance, False, self.disk_over_commit,
                'hostname', self.force, self.async_)
        self.mock_get.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=['numa_topology'],
                                              cell_down_support=False)

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

    def test_migrate_live_vtpm_not_supported(self):
        self._test_migrate_live_failed_with_exception(
            exception.OperationNotSupportedForVTPM(
                instance_uuid=uuids.instance, operation='foo'),
            expected_exc=webob.exc.HTTPConflict,
            check_response=False)

    def test_migrate_live_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_migrate_live_migration_with_unexpected_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationError(reason=''),
            expected_exc=webob.exc.HTTPInternalServerError,
            check_response=False)

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.api.openstack.common.'
                'instance_has_port_with_resource_request', return_value=True)
    def test_migrate_with_bandwidth_from_old_compute_not_supported(
            self, mock_has_res_req, mock_get_service):
        instance = self._stub_instance_get()

        mock_get_service.return_value = objects.Service(host=instance['host'])
        mock_get_service.return_value.version = 38

        self.assertRaises(
            webob.exc.HTTPConflict, self.controller._migrate, self.req,
            instance['uuid'], body={'migrate': None})

        mock_has_res_req.assert_called_once_with(
            instance['uuid'], self.controller.network_api)
        mock_get_service.assert_called_once_with(
            self.req.environ['nova.context'], instance['host'], 'nova-compute')


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
                                       self.async_), {})}
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


class MigrateServerTestsV230(MigrateServerTestsV225):
    force = False

    def setUp(self):
        super(MigrateServerTestsV230, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.30')

    def _test_live_migrate(self, force=False):
        if force is True:
            literal_force = 'true'
        else:
            literal_force = 'false'
        method_translations = {'_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': {'os-migrateLive': {'host': 'hostname',
                                      'block_migration': 'auto',
                                      'force': literal_force}}}
        args_map = {'_migrate_live': ((None, None, 'hostname', force,
                                       self.async_), {})}
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
    async_ = True

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

    def test_migrate_live_compute_host_not_found(self):
        body = {'os-migrateLive':
                {'host': 'hostname', 'block_migration': 'auto'}}
        exc = exception.ComputeHostNotFound(
                reason="Compute host %(host)s could not be found.",
                host='hostname')
        instance = self._stub_instance_get()

        with mock.patch.object(self.compute_api, 'live_migrate',
                               side_effect=exc) as mock_live_migrate:
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller._migrate_live,
                              self.req, instance.uuid, body=body)
            mock_live_migrate.assert_called_once_with(
                self.context, instance, None, self.disk_over_commit,
                'hostname', self.force, self.async_)
        self.mock_get.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=['numa_topology'],
                                              cell_down_support=False)

    def test_migrate_live_unexpected_error(self):
        body = {'os-migrateLive':
                {'host': 'hostname', 'block_migration': 'auto'}}
        exc = exception.InvalidHypervisorType(
                reason="The supplied hypervisor type of is invalid.")
        instance = self._stub_instance_get()

        with mock.patch.object(self.compute_api, 'live_migrate',
                               side_effect=exc) as mock_live_migrate:
            self.assertRaises(webob.exc.HTTPInternalServerError,
                              self.controller._migrate_live,
                              self.req, instance.uuid, body=body)
            mock_live_migrate.assert_called_once_with(
                self.context, instance, None, self.disk_over_commit,
                'hostname', self.force, self.async_)
        self.mock_get.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=['numa_topology'],
                                              cell_down_support=False)


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

    def test_migrate_to_same_host(self):
        exc_info = exception.CannotMigrateToSameHost()
        self._test_migrate_exception(exc_info, webob.exc.HTTPBadRequest)


class MigrateServerTestsV268(MigrateServerTestsV256):
    force = False

    def setUp(self):
        super(MigrateServerTestsV268, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.68')

    def test_live_migrate(self):
        method_translations = {'_migrate_live': 'live_migrate'}
        body_map = {'_migrate_live': {'os-migrateLive': {'host': 'hostname',
                                      'block_migration': 'auto'}}}
        args_map = {'_migrate_live': ((None, None, 'hostname', False,
                                       self.async_), {})}
        self._test_actions(['_migrate_live'], body_map=body_map,
                           method_translations=method_translations,
                           args_map=args_map)

    @mock.patch('nova.virt.hardware.get_mem_encryption_constraint',
                new=mock.Mock(return_value=True))
    @mock.patch.object(
        objects.instance.Instance, 'image_meta',
        new=objects.ImageMeta.from_dict({}))
    def test_live_migrate_sev_rejected(self):
        instance = self._stub_instance_get()
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': 'auto'}}
        ex = self.assertRaises(webob.exc.HTTPConflict,
                               self.controller._migrate_live,
                               self.req, fakes.FAKE_UUID, body=body)
        self.assertIn("Operation 'live-migration' not supported for "
                      "SEV-enabled instance (%s)" % instance.uuid,
                      six.text_type(ex))

    def test_live_migrate_with_forced_host(self):
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': 'auto',
                                   'force': 'true'}}
        ex = self.assertRaises(self.validation_error,
                               self.controller._migrate_live,
                               self.req, fakes.FAKE_UUID, body=body)
        self.assertIn('force', six.text_type(ex))
