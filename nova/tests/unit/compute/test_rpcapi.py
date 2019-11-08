# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for nova.compute.rpcapi
"""

import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import exception
from nova.objects import block_device as objects_block_dev
from nova.objects import migration as migration_obj
from nova.objects import service as service_obj
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_request_spec


class ComputeRpcAPITestCase(test.NoDBTestCase):

    def setUp(self):
        super(ComputeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        self.fake_flavor_obj = fake_flavor.fake_flavor_obj(self.context)
        self.fake_flavor = jsonutils.to_primitive(self.fake_flavor_obj)
        instance_attr = {'host': 'fake_host',
                         'instance_type_id': self.fake_flavor_obj['id'],
                         'instance_type': self.fake_flavor_obj}
        self.fake_instance_obj = fake_instance.fake_instance_obj(self.context,
                                                   **instance_attr)
        self.fake_instance = jsonutils.to_primitive(self.fake_instance_obj)
        self.fake_volume_bdm = objects_block_dev.BlockDeviceMapping(
                **fake_block_device.FakeDbBlockDeviceDict(
                    {'source_type': 'volume', 'destination_type': 'volume',
                     'instance_uuid': self.fake_instance_obj.uuid,
                     'volume_id': 'fake-volume-id'}))
        self.fake_request_spec_obj = fake_request_spec.fake_spec_obj()
        # FIXME(melwitt): Temporary while things have no mappings
        self.patcher1 = mock.patch('nova.objects.InstanceMapping.'
                                   'get_by_instance_uuid')
        self.patcher2 = mock.patch('nova.objects.HostMapping.get_by_host')
        mock_inst_mapping = self.patcher1.start()
        mock_host_mapping = self.patcher2.start()
        mock_inst_mapping.side_effect = exception.InstanceMappingNotFound(
                uuid=self.fake_instance_obj.uuid)
        mock_host_mapping.side_effect = exception.HostMappingNotFound(
                name=self.fake_instance_obj.host)

    def tearDown(self):
        super(ComputeRpcAPITestCase, self).tearDown()
        self.patcher1.stop()
        self.patcher2.stop()

    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_auto_pin(self, mock_get_min):
        mock_get_min.return_value = 1
        self.flags(compute='auto', group='upgrade_levels')
        compute_rpcapi.LAST_VERSION = None
        rpcapi = compute_rpcapi.ComputeAPI()
        self.assertEqual('4.4', rpcapi.router.version_cap)
        mock_get_min.assert_called_once_with(mock.ANY, ['nova-compute'])

    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_auto_pin_fails_if_too_old(self, mock_get_min):
        mock_get_min.return_value = 1955
        self.flags(compute='auto', group='upgrade_levels')
        self.assertRaises(exception.ServiceTooOld,
                          compute_rpcapi.ComputeAPI()._determine_version_cap,
                          mock.Mock)

    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_auto_pin_with_service_version_zero(self, mock_get_min):
        mock_get_min.return_value = 0
        self.flags(compute='auto', group='upgrade_levels')
        compute_rpcapi.LAST_VERSION = None
        rpcapi = compute_rpcapi.ComputeAPI()
        history = service_obj.SERVICE_VERSION_HISTORY
        current_version = history[service_obj.SERVICE_VERSION]['compute_rpc']
        self.assertEqual(current_version, rpcapi.router.version_cap)
        mock_get_min.assert_called_once_with(mock.ANY, ['nova-compute'])
        self.assertIsNone(compute_rpcapi.LAST_VERSION)

    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_auto_pin_caches(self, mock_get_min):
        mock_get_min.return_value = 1
        self.flags(compute='auto', group='upgrade_levels')
        compute_rpcapi.LAST_VERSION = None
        api = compute_rpcapi.ComputeAPI()
        for x in range(2):
            api._determine_version_cap(mock.Mock())
        mock_get_min.assert_called_once_with(mock.ANY, ['nova-compute'])
        self.assertEqual('4.4', compute_rpcapi.LAST_VERSION)

    def _test_compute_api(self, method, rpc_method,
                          expected_args=None, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = kwargs.pop('rpcapi_class', compute_rpcapi.ComputeAPI)()
        self.assertIsNotNone(rpcapi.router)
        self.assertEqual(rpcapi.router.target.topic,
                         compute_rpcapi.RPC_TOPIC)

        # This test wants to run the real prepare function, so must use
        # a real client object
        default_client = rpcapi.router.default_client

        orig_prepare = default_client.prepare
        base_version = rpcapi.router.target.version
        expected_version = kwargs.pop('version', base_version)

        prepare_extra_kwargs = {}
        cm_timeout = kwargs.pop('call_monitor_timeout', None)
        timeout = kwargs.pop('timeout', None)
        if cm_timeout:
            prepare_extra_kwargs['call_monitor_timeout'] = cm_timeout
        if timeout:
            prepare_extra_kwargs['timeout'] = timeout

        expected_kwargs = kwargs.copy()
        if expected_args:
            expected_kwargs.update(expected_args)
        if 'host_param' in expected_kwargs:
            expected_kwargs['host'] = expected_kwargs.pop('host_param')
        else:
            expected_kwargs.pop('host', None)

        cast_and_call = ['confirm_resize', 'stop_instance']
        if rpc_method == 'call' and method in cast_and_call:
            if method == 'confirm_resize':
                kwargs['cast'] = False
            else:
                kwargs['do_cast'] = False
        if 'host' in kwargs:
            host = kwargs['host']
        elif 'instances' in kwargs:
            host = kwargs['instances'][0]['host']
        elif 'destination' in kwargs:
            host = expected_kwargs.pop('destination')
        else:
            host = kwargs['instance']['host']

        if method == 'rebuild_instance' and 'node' in expected_kwargs:
            expected_kwargs['scheduled_node'] = expected_kwargs.pop('node')

        with test.nested(
            mock.patch.object(default_client, rpc_method),
            mock.patch.object(default_client, 'prepare'),
            mock.patch.object(default_client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):
            prepare_mock.return_value = default_client
            if '_return_value' in kwargs:
                rpc_mock.return_value = kwargs.pop('_return_value')
                del expected_kwargs['_return_value']
            elif rpc_method == 'call':
                rpc_mock.return_value = 'foo'
            else:
                rpc_mock.return_value = None
            csv_mock.side_effect = (
                lambda v: orig_prepare(version=v).can_send_version())

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, rpc_mock.return_value)

            prepare_mock.assert_called_once_with(version=expected_version,
                                                 server=host,
                                                 **prepare_extra_kwargs)
            rpc_mock.assert_called_once_with(ctxt, method, **expected_kwargs)

    def test_add_aggregate_host(self):
        self._test_compute_api('add_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance_obj, network_id='id',
                version='5.0')

    def test_attach_interface(self):
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance_obj, network_id='id',
                port_id='id2', version='5.0', requested_ip='192.168.1.50',
                tag='foo')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance_obj, bdm=self.fake_volume_bdm,
                version='5.0')

    def test_change_instance_metadata(self):
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance_obj, diff={}, version='5.0')

    def test_check_instance_shared_storage(self):
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance_obj, data='foo',
                version='5.0')

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host')

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host')

    def test_detach_interface(self):
        self._test_compute_api('detach_interface', 'cast',
                version='5.0', instance=self.fake_instance_obj,
                port_id='fake_id')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                attachment_id='fake_id', version='5.0')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                request_spec=self.fake_request_spec_obj, version='5.2')

    def test_finish_resize_old_compute(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        # So we expect that the messages is backported therefore the
        # request_spec is dropped
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.finish_resize(
            ctxt, instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, image='image',
            disk_info='disk_info', host='host',
            request_spec=self.fake_request_spec_obj)

        mock_client.can_send_version.assert_called_once_with('5.2')
        mock_client.prepare.assert_called_with(
            server='host', version='5.0')
        mock_cctx.cast.assert_called_with(
            ctxt, 'finish_resize', instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, image='image',
            disk_info='disk_info')

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', request_spec=self.fake_request_spec_obj,
                version='5.2')

    def test_finish_revert_resize_old_compute(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        # So we expect that the messages is backported therefore the
        # request_spec is dropped
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.finish_revert_resize(
            ctxt, instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, host='host',
            request_spec=self.fake_request_spec_obj)

        mock_client.can_send_version.assert_called_once_with('5.2')
        mock_client.prepare.assert_called_with(
            server='host', version='5.0')
        mock_cctx.cast.assert_called_with(
            ctxt, 'finish_revert_resize', instance=self.fake_instance_obj,
            migration=mock.sentinel.migration)

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance_obj, tail_length='tl',
                version='5.0')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

    def test_get_console_topic(self):
        self._test_compute_api('get_console_topic', 'call', host='host')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance_obj, version='5.0')

    def test_get_instance_diagnostics(self):
        expected_args = {'instance': self.fake_instance_obj}
        self._test_compute_api('get_instance_diagnostics', 'call',
                expected_args, instance=self.fake_instance_obj,
                version='5.0')

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='5.0')

    def test_get_spice_console(self):
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='5.0')

    def test_get_rdp_console(self):
        self._test_compute_api('get_rdp_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='5.0')

    def test_get_serial_console(self):
        self._test_compute_api('get_serial_console', 'call',
                instance=self.fake_instance_obj, console_type='serial',
                version='5.0')

    def test_get_mks_console(self):
        self._test_compute_api('get_mks_console', 'call',
                instance=self.fake_instance_obj, console_type='webmks',
                version='5.0')

    def test_validate_console_port(self):
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance_obj, port="5900",
                console_type="novnc", version='5.0')

    def test_host_maintenance_mode(self):
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

    def test_host_power_action(self):
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

    def test_inject_network_info(self):
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance_obj)

    def test_live_migration(self):
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance_obj, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migration='migration',
                migrate_data={}, version='5.0')

    def test_live_migration_force_complete(self):
        migration = migration_obj.Migration()
        migration.id = 1
        migration.source_compute = 'fake'
        ctxt = context.RequestContext('fake_user', 'fake_project')
        version = '5.0'
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        mock_client.can_send_version.return_value = True
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.live_migration_force_complete(ctxt, self.fake_instance_obj,
                                             migration)
        mock_client.prepare.assert_called_with(server=migration.source_compute,
                                               version=version)
        mock_cctx.cast.assert_called_with(ctxt,
                                          'live_migration_force_complete',
                                          instance=self.fake_instance_obj)

    def test_live_migration_abort(self):
        self._test_compute_api('live_migration_abort', 'cast',
                instance=self.fake_instance_obj,
                migration_id='1', version='5.0')

    def test_post_live_migration_at_destination(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('post_live_migration_at_destination', 'call',
                instance=self.fake_instance_obj,
                block_migration='block_migration', host='host', version='5.0',
                timeout=1234, call_monitor_timeout=60)

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_soft_delete_instance(self):
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance_obj)

    def test_swap_volume(self):
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance_obj, old_volume_id='oldid',
                new_volume_id='newid', new_attachment_id=uuids.attachment_id,
                version='5.0')

    def test_restore_instance(self):
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance_obj, version='5.0')

    def test_pre_live_migration(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance_obj,
                block_migration='block_migration', disk='disk', host='host',
                migrate_data=None, version='5.0',
                call_monitor_timeout=60, timeout=1234)

    def test_supports_numa_live_migration(self):
        mock_client = mock.MagicMock()
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        rpcapi.router.client.return_value = mock_client

        ctxt = context.RequestContext('fake_user', 'fake_project'),
        mock_client.can_send_version.return_value = False
        self.assertFalse(rpcapi.supports_numa_live_migration(ctxt))
        mock_client.can_send_version.return_value = True
        self.assertTrue(rpcapi.supports_numa_live_migration(ctxt))
        mock_client.can_send_version.assert_has_calls(
            [mock.call('5.3'), mock.call('5.3')])

    def test_check_can_live_migrate_destination(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                               instance=self.fake_instance_obj,
                               destination='dest',
                               block_migration=False,
                               disk_over_commit=False,
                               version='5.3', call_monitor_timeout=60,
                               migration='migration',
                               limits='limits',
                               timeout=1234)

    def test_check_can_live_migrate_destination_backlevel(self):
        mock_cctxt = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_client.can_send_version.return_value = False
        mock_client.prepare.return_value = mock_cctxt

        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        rpcapi.router.client.return_value = mock_client

        ctxt = context.RequestContext('fake_user', 'fake_project'),
        rpcapi.check_can_live_migrate_destination(
            ctxt, instance=self.fake_instance_obj,
            destination='dest',
            block_migration=False,
            disk_over_commit=False,
            migration='migration',
            limits='limits')

        mock_client.prepare.assert_called_with(server='dest', version='5.0',
                                               call_monitor_timeout=mock.ANY,
                                               timeout=mock.ANY)
        mock_cctxt.call.assert_called_once_with(
            ctxt, 'check_can_live_migrate_destination',
            instance=self.fake_instance_obj, block_migration=False,
            disk_over_commit=False)

    def test_drop_move_claim_at_destination(self):
        self._test_compute_api('drop_move_claim_at_destination', 'call',
                               instance=self.fake_instance_obj, host='host',
                               version='5.3', _return_value=None)

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj,
                instance_type=self.fake_flavor_obj,
                image='fake_image', host='host',
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                migration='migration',
                node='node', clean_shutdown=True, host_list=None,
                version='5.1')

    def test_reboot_instance(self):
        self.maxDiff = None
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance_obj,
                block_device_info={},
                reboot_type='type')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance_obj, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                preserve_ephemeral=True, migration=None, node=None,
                limits=None, request_spec=None, version='5.0')

    def test_reserve_block_device_name(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance_obj, device='device',
                volume_id='id', disk_bus='ide', device_type='cdrom',
                tag='foo', multiattach=True, version='5.0',
                timeout=1234, call_monitor_timeout=60,
                _return_value=objects_block_dev.BlockDeviceMapping())

    def test_refresh_instance_security_rules(self):
        expected_args = {'instance': self.fake_instance_obj}
        self._test_compute_api('refresh_instance_security_rules', 'cast',
                expected_args, host='fake_host',
                instance=self.fake_instance_obj, version='5.0')

    def test_remove_aggregate_host(self):
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance_obj, address='addr',
                version='5.0')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance_obj, volume_id='id', host='host',
                version='5.0')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref',
            clean_shutdown=True, version='5.0')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance_obj)

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', instance_type=self.fake_flavor_obj,
                clean_shutdown=True, request_spec=self.fake_request_spec_obj,
                version='5.2')

    def test_resize_instance_old_compute(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        # So we expect that the messages is backported therefore the
        # request_spec is dropped
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.resize_instance(
            ctxt, instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, image='image',
            instance_type='instance_type', clean_shutdown=True,
            request_spec=self.fake_request_spec_obj)

        mock_client.can_send_version.assert_called_once_with('5.2')
        mock_client.prepare.assert_called_with(
            server=self.fake_instance_obj.host, version='5.0')
        mock_cctx.cast.assert_called_with(
            ctxt, 'resize_instance', instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, image='image',
            instance_type='instance_type', clean_shutdown=True)

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', request_spec=self.fake_request_spec_obj,
                version='5.2')

    def test_revert_resize_old_compute(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        # So we expect that the messages is backported therefore the
        # request_spec is dropped
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.revert_resize(
            ctxt, instance=self.fake_instance_obj,
            migration=mock.sentinel.migration, host='host',
            request_spec=self.fake_request_spec_obj)

        mock_client.can_send_version.assert_called_once_with('5.2')
        mock_client.prepare.assert_called_with(
            server='host', version='5.0')
        mock_cctx.cast.assert_called_with(
            ctxt, 'revert_resize', instance=self.fake_instance_obj,
            migration=mock.sentinel.migration)

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance_obj, new_pass='pw',
                version='5.0')

    def test_set_host_enabled(self):
        self.flags(long_rpc_timeout=600, rpc_response_timeout=120)
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host',
                call_monitor_timeout=120, timeout=600)

    def test_get_host_uptime(self):
        self._test_compute_api('get_host_uptime', 'call', host='host')

    def test_backup_instance(self):
        self._test_compute_api('backup_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id',
                backup_type='type', rotation='rotation')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance_obj)

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='5.0')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='5.0')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance_obj, bdms=[],
                version='5.0')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance_obj, version='5.0')

    def test_shelve_instance(self):
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                clean_shutdown=True, version='5.0')

    def test_shelve_offload_instance(self):
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='5.0')

    def test_unshelve_instance(self):
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                filter_properties={'fakeprop': 'fakeval'}, node='node',
                request_spec=self.fake_request_spec_obj,
                version='5.2')

    def test_unshelve_instance_old_compute(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        rpcapi.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        rpcapi.router.client.return_value = mock_client
        # So we expect that the messages is backported therefore the
        # request_spec is dropped
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rpcapi.unshelve_instance(
            ctxt, instance=self.fake_instance_obj,
            host='host', request_spec=self.fake_request_spec_obj,
            image='image')

        mock_client.can_send_version.assert_called_once_with('5.2')
        mock_client.prepare.assert_called_with(
            server='host', version='5.0')
        mock_cctx.cast.assert_called_with(
            ctxt, 'unshelve_instance', instance=self.fake_instance_obj,
            image='image', filter_properties=None, node=None)

    def test_volume_snapshot_create(self):
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                create_info={}, version='5.0')

    def test_volume_snapshot_delete(self):
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='5.0')

    def test_external_instance_event(self):
        self._test_compute_api('external_instance_event', 'cast',
                               instances=[self.fake_instance_obj],
                               events=['event'],
                               version='5.0')

    def test_build_and_run_instance(self):
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks=['network1'], security_groups=None,
                block_device_mapping=None, node='node', limits=[],
                host_list=None, version='5.0')

    def test_quiesce_instance(self):
        self._test_compute_api('quiesce_instance', 'call',
                instance=self.fake_instance_obj, version='5.0')

    def test_unquiesce_instance(self):
        self._test_compute_api('unquiesce_instance', 'cast',
                instance=self.fake_instance_obj, mapping=None, version='5.0')

    def test_trigger_crash_dump(self):
        self._test_compute_api('trigger_crash_dump', 'cast',
                instance=self.fake_instance_obj, version='5.0')

    @mock.patch('nova.compute.rpcapi.LOG')
    @mock.patch('nova.objects.Service.get_minimum_version')
    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_version_cap_no_computes_log_once(self, mock_allcells, mock_minver,
                                              mock_log):
        self.flags(connection=None, group='api_database')
        self.flags(compute='auto', group='upgrade_levels')
        mock_minver.return_value = 0
        api = compute_rpcapi.ComputeAPI()
        for x in range(2):
            api._determine_version_cap(mock.Mock())
        mock_allcells.assert_not_called()
        mock_minver.assert_has_calls([
            mock.call(mock.ANY, 'nova-compute'),
            mock.call(mock.ANY, 'nova-compute')])

    @mock.patch('nova.objects.Service.get_minimum_version')
    @mock.patch('nova.objects.service.get_minimum_version_all_cells')
    def test_version_cap_all_cells(self, mock_allcells, mock_minver):
        self.flags(connection='sqlite:///', group='api_database')
        self.flags(compute='auto', group='upgrade_levels')
        mock_allcells.return_value = 0
        compute_rpcapi.ComputeAPI()._determine_version_cap(mock.Mock())
        mock_allcells.assert_called_once_with(mock.ANY, ['nova-compute'])
        mock_minver.assert_not_called()

    @mock.patch('nova.compute.rpcapi.LOG.error')
    @mock.patch('nova.objects.Service.get_minimum_version')
    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                side_effect=exception.DBNotAllowed(binary='nova-compute'))
    def test_version_cap_all_cells_no_access(self, mock_allcells, mock_minver,
                                             mock_log_error):
        """Tests a scenario where nova-compute is configured with a connection
        to the API database and fails trying to get the minium nova-compute
        service version across all cells because nova-compute is configured to
        not allow direct database access.
        """
        self.flags(connection='sqlite:///', group='api_database')
        self.assertRaises(exception.DBNotAllowed,
                          compute_rpcapi.ComputeAPI()._determine_version_cap,
                          mock.Mock())
        mock_allcells.assert_called_once_with(mock.ANY, ['nova-compute'])
        mock_minver.assert_not_called()
        # Make sure the expected error was logged.
        mock_log_error.assert_called_once_with(
            'This service is configured for access to the '
            'API database but is not allowed to directly '
            'access the database. You should run this '
            'service without the [api_database]/connection '
            'config option.')
