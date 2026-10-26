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

from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import exception
from nova import objects
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
        instance_attr = {
            'host': 'fake_host',
            'instance_type_id': self.fake_flavor_obj['id'],
            'flavor': self.fake_flavor_obj,
        }
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
        topic_alt = kwargs.pop('topic_alt', None)
        if cm_timeout:
            prepare_extra_kwargs['call_monitor_timeout'] = cm_timeout
        if timeout:
            prepare_extra_kwargs['timeout'] = timeout
        if topic_alt:
            prepare_extra_kwargs['topic'] = topic_alt

        # NOTE(sbauza): If expected args are provided, we need to use them
        # for the expected kwargs and just add the needed _return_value that
        # is passed by kwargs.
        if expected_args:
            expected_kwargs = expected_args.copy()
            if '_return_value' in kwargs:
                # Copy the existing return value
                expected_kwargs['_return_value'] = kwargs['_return_value']
        # NOTE(sbauza) : No expected args were provided so let's just use the
        # kwargs as also the expected args.
        else:
            expected_kwargs = kwargs.copy()
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
        elif 'prepare_server' in kwargs:
            # This is the "server" kwarg to the prepare() method so remove it
            # from both kwargs that go to the actual RPC method call.
            # NOTE(sbauza): If we copy expected args from the provided kwargs,
            # sometimes we don't have a prepare_server argument in them hence
            # the default None value.
            expected_kwargs.pop('prepare_server', None)
            host = kwargs.pop('prepare_server')
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

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance_obj, network_id='id',
                version='6.0')

    def test_attach_interface(self):
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance_obj, network_id='id',
                port_id='id2', version='6.0', requested_ip='192.168.1.50',
                tag='foo')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance_obj, bdm=self.fake_volume_bdm,
                version='6.0')

    def test_check_instance_shared_storage(self):
        expected_args = {'data': 'foo'}
        self._test_compute_api('check_instance_shared_storage', 'call',
                expected_args,
                instance=self.fake_instance_obj, data='foo',
                version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

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
                version='6.0', instance=self.fake_instance_obj,
                port_id='fake_id')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                attachment_id='fake_id', version='6.0')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                request_spec=self.fake_request_spec_obj, version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', request_spec=self.fake_request_spec_obj,
                version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance_obj, tail_length='tl',
                version='6.0')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance_obj, version='6.0')

    def test_get_instance_diagnostics(self):
        expected_args = {'instance': self.fake_instance_obj}
        self._test_compute_api('get_instance_diagnostics', 'call',
                expected_args, instance=self.fake_instance_obj,
                version='6.0')

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='6.0')

    def test_get_spice_console(self):
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='6.0')

    def test_get_serial_console(self):
        self._test_compute_api('get_serial_console', 'call',
                instance=self.fake_instance_obj, console_type='serial',
                version='6.0')

    def test_get_mks_console(self):
        self._test_compute_api('get_mks_console', 'call',
                instance=self.fake_instance_obj, console_type='webmks',
                version='6.0')

    def test_validate_console_port(self):
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance_obj, port="5900",
                console_type="novnc", version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

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
                migrate_data={}, version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_live_migration_force_complete(self):
        migration = migration_obj.Migration()
        migration.id = 1
        migration.source_compute = 'fake'
        ctxt = context.RequestContext('fake_user', 'fake_project')
        version = '6.0'
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
                migration_id='1', version='6.0')

    def test_post_live_migration_at_destination(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('post_live_migration_at_destination', 'call',
                instance=self.fake_instance_obj,
                block_migration='block_migration', host='host', version='6.0',
                timeout=1234, call_monitor_timeout=60,
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

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
                version='6.0')

    def test_restore_instance(self):
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance_obj, version='6.0')

    def test_pre_live_migration(self):
        self.flags(long_rpc_timeout=1234)
        expected_args = {'instance': self.fake_instance_obj,
                         'disk': 'disk', 'host': 'host', 'migrate_data': None}
        self._test_compute_api('pre_live_migration', 'call',
                expected_args, instance=self.fake_instance_obj,
                block_migration='block_migration', disk='disk', host='host',
                migrate_data=None, version='6.0',
                call_monitor_timeout=60, timeout=1234,
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_check_can_live_migrate_destination(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                               instance=self.fake_instance_obj,
                               destination='dest',
                               block_migration=False,
                               disk_over_commit=False,
                               version='6.0', call_monitor_timeout=60,
                               migration='migration',
                               limits='limits',
                               timeout=1234)

    def test_rollback_live_migration_at_destination(self):
        self._test_compute_api('rollback_live_migration_at_destination',
                               'cast', instance=self.fake_instance_obj,
                               host='host', destroy_disks=True,
                               migrate_data=None, version='6.0',
                               _return_value=None,
                               topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_drop_move_claim_at_destination(self):
        self._test_compute_api('drop_move_claim_at_destination', 'call',
                               instance=self.fake_instance_obj, host='host',
                               version='6.0', _return_value=None,
                               topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj,
                flavor=self.fake_flavor_obj,
                image='fake_image', host='host',
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                migration='migration',
                node='node', clean_shutdown=True, host_list=None,
                version='6.0')

    def test_prep_snapshot_based_resize_at_dest(self):
        """Tests happy path for prep_snapshot_based_resize_at_dest rpc call"""
        expected_args = {'instance': self.fake_instance_obj,
                        'flavor': self.fake_flavor_obj,
                        'nodename': 'node',
                        'migration': migration_obj.Migration(),
                        'limits': {},
                        'destination': 'dest'}
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'prep_snapshot_based_resize_at_dest', 'call',
            expected_args,
            # compute method kwargs
            **expected_args,
            request_spec=objects.RequestSpec(),
            # client.prepare kwargs
            version='6.0', call_monitor_timeout=60, timeout=1234,
            # assert the expected return value
            _return_value=mock.sentinel.migration_context)

    def test_prep_snapshot_based_resize_at_source(self):
        """Tests happy path for prep_snapshot_based_resize_at_source rpc call
        """
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'prep_snapshot_based_resize_at_source', 'call',
            # compute method kwargs
            instance=self.fake_instance_obj,
            migration=migration_obj.Migration(),
            snapshot_id=uuids.snapshot_id,
            # client.prepare kwargs
            version='6.0', call_monitor_timeout=60, timeout=1234,
            topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_finish_snapshot_based_resize_at_dest(self):
        """Tests happy path for finish_snapshot_based_resize_at_dest."""
        expected_args = {'instance': self.fake_instance_obj,
                         'migration': migration_obj.Migration(
                            dest_compute='dest'),
                         'snapshot_id': uuids.snapshot_id}
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'finish_snapshot_based_resize_at_dest', 'call',
            expected_args,
            # compute method kwargs
            **expected_args,
            request_spec=objects.RequestSpec(),
            # client.prepare kwargs
            version='6.0', prepare_server='dest',
            call_monitor_timeout=60, timeout=1234,
            topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_confirm_snapshot_based_resize_at_source(self):
        """Tests happy path for confirm_snapshot_based_resize_at_source."""
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'confirm_snapshot_based_resize_at_source', 'call',
            # compute method kwargs
            instance=self.fake_instance_obj,
            migration=migration_obj.Migration(source_compute='source'),
            # client.prepare kwargs
            version='6.0', prepare_server='source',
            call_monitor_timeout=60, timeout=1234)

    def test_revert_snapshot_based_resize_at_dest(self):
        """Tests happy path for revert_snapshot_based_resize_at_dest."""
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'revert_snapshot_based_resize_at_dest', 'call',
            # compute method kwargs
            instance=self.fake_instance_obj,
            migration=migration_obj.Migration(dest_compute='dest'),
            # client.prepare kwargs
            version='6.0', prepare_server='dest',
            call_monitor_timeout=60, timeout=1234)

    def test_finish_revert_snapshot_based_resize_at_source(self):
        """Tests happy path for finish_revert_snapshot_based_resize_at_source.
        """
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api(
            'finish_revert_snapshot_based_resize_at_source', 'call',
            # compute method kwargs
            instance=self.fake_instance_obj,
            migration=migration_obj.Migration(source_compute='source'),
            # client.prepare kwargs
            version='6.0', prepare_server='source',
            call_monitor_timeout=60, timeout=1234,
            topic_alt='compute-alt')

    def test_reboot_instance(self):
        self.maxDiff = None
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance_obj,
                block_device_info={},
                reboot_type='type')

    def test_rebuild_instance(self):
        # With rpcapi 5.12, when a list of accel_uuids is passed as a param,
        # that list must be passed to the client. That is tested in
        # _test_compute_api with rpc_mock.assert, where expected_kwargs
        # must have the accel_uuids.
        self._test_compute_api(
            'rebuild_instance', 'cast', new_pass='None',
            injected_files='None', image_ref='None', orig_image_ref='None',
            bdms=[], instance=self.fake_instance_obj, host='new_host',
            orig_sys_metadata=None, recreate=True, on_shared_storage=True,
            preserve_ephemeral=True, migration=None, node=None,
            limits=None, request_spec=None, accel_uuids=[],
            reimage_boot_volume=False, target_state=None,
            version='6.2')

    def test_rebuild_instance_vol_backed_old_rpcapi(self):
        # With rpcapi < 6.1, if reimage_boot_volume is True then we
        # should raise error.
        ctxt = context.RequestContext('fake_user', 'fake_project')
        compute_api = compute_rpcapi.ComputeAPI()
        compute_api.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        compute_api.router.client.return_value = mock_client
        # Force can_send_version to [False, True, True], so that 6.0
        # version is used.
        mock_client.can_send_version.side_effect = [False, False, True, True]
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rebuild_args = {
            'new_pass': 'admin_password',
            'injected_files': 'files_to_inject',
            'image_ref': uuids.image_ref,
            'orig_image_ref': uuids.orig_image_ref,
            'orig_sys_metadata': 'orig_sys_meta',
            'bdms': {},
            'recreate': False,
            'on_shared_storage': False,
            'preserve_ephemeral': False,
            'request_spec': None,
            'migration': None,
            'limits': None,
            'accel_uuids': [],
            'reimage_boot_volume': True,
            'target_state': None,
        }
        self.assertRaises(
            exception.NovaException, compute_api.rebuild_instance,
            ctxt, instance=self.fake_instance_obj,
            node=None, host=None, **rebuild_args)
        mock_client.can_send_version.assert_has_calls([mock.call('6.2')])

    def test_rebuild_instance_evacuate_old_rpcapi(self):
        # With rpcapi < 6.2, if evacuate we should raise error.
        ctxt = context.RequestContext('fake_user', 'fake_project')
        compute_api = compute_rpcapi.ComputeAPI()
        compute_api.router.client = mock.Mock()
        mock_client = mock.MagicMock()
        compute_api.router.client.return_value = mock_client
        # Force can_send_version to return False.
        mock_client.can_send_version.return_value = False
        mock_cctx = mock.MagicMock()
        mock_client.prepare.return_value = mock_cctx
        rebuild_args = {
            'new_pass': 'admin_password',
            'injected_files': 'files_to_inject',
            'image_ref': uuids.image_ref,
            'orig_image_ref': uuids.orig_image_ref,
            'orig_sys_metadata': 'orig_sys_meta',
            'bdms': {},
            'recreate': False,
            'on_shared_storage': False,
            'preserve_ephemeral': False,
            'request_spec': None,
            'migration': None,
            'limits': None,
            'accel_uuids': [],
            'reimage_boot_volume': True,
            'target_state': 'stopped',
        }
        self.assertRaises(
            exception.UnsupportedRPCVersion,
            compute_api.rebuild_instance,
            ctxt, instance=self.fake_instance_obj,
            node=None, host=None, **rebuild_args)

    def test_reserve_block_device_name(self):
        self.flags(long_rpc_timeout=1234)
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance_obj, device='device',
                volume_id='id', disk_bus='ide', device_type='cdrom',
                tag='foo', multiattach=True, version='6.0',
                timeout=1234, call_monitor_timeout=60,
                _return_value=objects_block_dev.BlockDeviceMapping())

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance_obj, address='addr',
                version='6.0')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance_obj, volume_id='id', host='host',
                delete_attachment=True, version='6.3',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref',
            clean_shutdown=True, version='6.0')

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', flavor=self.fake_flavor_obj,
                clean_shutdown=True, request_spec=self.fake_request_spec_obj,
                version='6.0',
                topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', request_spec=self.fake_request_spec_obj,
                version='6.0')

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance_obj, new_pass='pw',
                version='6.0')

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
                clean_shutdown=True, version='6.0')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='6.0')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance_obj, bdms=[],
                version='6.0')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance_obj, version='6.0')

    def test_shelve_instance(self):
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                clean_shutdown=True, accel_uuids=None, version='6.0')

    def test_shelve_offload_instance(self):
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, accel_uuids=None, version='6.0')

    def test_unshelve_instance(self):
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                filter_properties={'fakeprop': 'fakeval'}, node='node',
                request_spec=self.fake_request_spec_obj, accel_uuids=None,
                version='6.0')

    def test_cache_image(self):
        self._test_compute_api('cache_images', 'call',
                               host='host', image_ids=['image'],
                               call_monitor_timeout=60, timeout=1800,
                               version='6.0')

    def test_volume_snapshot_create(self):
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                create_info={}, version='6.0')

    def test_volume_snapshot_delete(self):
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='6.0')

    def test_external_instance_event(self):
        self._test_compute_api('external_instance_event', 'cast',
                               instances=[self.fake_instance_obj],
                               events=['event'],
                               version='6.0',
                               topic_alt=compute_rpcapi.RPC_TOPIC_ALT)

    def test_build_and_run_instance(self):
        # With rpcapi 5.11, when a list of accel_uuids is passed as a param,
        # that list must be passed to the client. That is tested in
        # _test_compute_api with rpc_mock.assert, where expected_kwargs
        # must have the accel_uuids.
        accel_uuids = ['938af7f9-f136-4e5a-bdbe-3b6feab54311']
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks=['network1'], security_groups=None,
                block_device_mapping=None, node='node', limits=[],
                host_list=None, accel_uuids=accel_uuids, version='6.0')

    def test_quiesce_instance(self):
        self._test_compute_api('quiesce_instance', 'call',
                instance=self.fake_instance_obj, version='6.0')

    def test_unquiesce_instance(self):
        self._test_compute_api('unquiesce_instance', 'cast',
                instance=self.fake_instance_obj, mapping=None, version='6.0')

    def test_trigger_crash_dump(self):
        self._test_compute_api('trigger_crash_dump', 'cast',
                instance=self.fake_instance_obj, version='6.0')

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
        to the API database and fails trying to get the minimum nova-compute
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

    def get_fake_share_mapping(self):
        share_mapping = objects.ShareMapping(self.context)
        share_mapping.uuid = uuids.share_mapping
        share_mapping.instance_uuid = uuids.instance
        share_mapping.share_id = uuids.share
        share_mapping.status = 'inactive'
        share_mapping.tag = 'fake_tag'
        share_mapping.export_location = '192.168.122.152:/manila/share'
        share_mapping.share_proto = 'NFS'
        return share_mapping

    def test_allow_share(self):
        self._test_compute_api(
            'allow_share',
            'cast',
            instance=self.fake_instance_obj,
            share_mapping=self.get_fake_share_mapping(),
            version='6.4')

    def test_deny_share(self):
        self._test_compute_api(
            'deny_share',
            'cast',
            instance=self.fake_instance_obj,
            share_mapping=self.get_fake_share_mapping(),
            version='6.4')

    def test_prepare_for_alt_rpcserver_select_topic_alt(self):
        rpcapi = compute_rpcapi.ComputeAPI()
        mock_client = mock.MagicMock()
        mock_client.can_send_version.return_value = True
        rpcapi.prepare_for_alt_rpcserver(
            mock_client, server='fake_host', version='6.5')
        mock_client.can_send_version.assert_called_once_with('6.5')
        mock_client.prepare.assert_called_once_with(
            server='fake_host',
            version='6.5',
            topic=compute_rpcapi.RPC_TOPIC_ALT)

    def test_prepare_for_alt_rpcserver_fallback_topic_for_old_compute(self):
        rpcapi = compute_rpcapi.ComputeAPI()
        mock_client = mock.MagicMock()
        mock_client.can_send_version.return_value = False
        rpcapi.prepare_for_alt_rpcserver(
            mock_client, server='fake_host', version='6.0')
        mock_client.can_send_version.assert_called_once_with('6.5')
        mock_client.prepare.assert_called_once_with(
            server='fake_host',
            version='6.0',
            topic=compute_rpcapi.RPC_TOPIC)

    def test_prepare_for_alt_rpcserver_with_extra_kwargs(self):
        rpcapi = compute_rpcapi.ComputeAPI()
        mock_client = mock.MagicMock()
        mock_client.can_send_version.return_value = True
        rpcapi.prepare_for_alt_rpcserver(
            mock_client,
            server='fake_host',
            version='6.5',
            call_monitor_timeout=60,
            timeout=120)
        mock_client.can_send_version.assert_called_once_with('6.5')
        mock_client.prepare.assert_called_once_with(
            server='fake_host',
            version='6.5',
            topic=compute_rpcapi.RPC_TOPIC_ALT,
            call_monitor_timeout=60,
            timeout=120)
