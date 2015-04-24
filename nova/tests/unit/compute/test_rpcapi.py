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

import contextlib

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova.objects import block_device as objects_block_dev
from nova.objects import compute_node as objects_compute_node
from nova.objects import network_request as objects_network_request
from nova.objects import numa as objects_numa
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance

CONF = cfg.CONF


class ComputeRpcAPITestCase(test.NoDBTestCase):

    def setUp(self):
        super(ComputeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        instance_attr = {'host': 'fake_host',
                         'instance_type_id': 1}
        self.fake_instance_obj = fake_instance.fake_instance_obj(self.context,
                                                   **instance_attr)
        self.fake_instance = jsonutils.to_primitive(self.fake_instance_obj)
        self.fake_volume_bdm = jsonutils.to_primitive(
                fake_block_device.FakeDbBlockDeviceDict(
                    {'source_type': 'volume', 'destination_type': 'volume',
                     'instance_uuid': self.fake_instance['uuid'],
                     'volume_id': 'fake-volume-id'}))

    def test_serialized_instance_has_name(self):
        self.assertIn('name', self.fake_instance)

    def _test_compute_api(self, method, rpc_method,
                          assert_dict=False, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = kwargs.pop('rpcapi_class', compute_rpcapi.ComputeAPI)()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic, CONF.compute_topic)

        orig_prepare = rpcapi.client.prepare
        # TODO(danms): Remove this special case when we drop 3.x
        if CONF.upgrade_levels.compute == 'kilo':
            base_version = '3.0'
        else:
            base_version = rpcapi.client.target.version
        expected_version = kwargs.pop('version', base_version)
        nova_network = kwargs.pop('nova_network', False)

        expected_kwargs = kwargs.copy()
        if ('requested_networks' in expected_kwargs and
               expected_version == '3.23'):
            expected_kwargs['requested_networks'] = []
            for requested_network in kwargs['requested_networks']:
                if not nova_network:
                    expected_kwargs['requested_networks'].append(
                        (requested_network.network_id,
                         str(requested_network.address),
                         requested_network.port_id))
                else:
                    expected_kwargs['requested_networks'].append(
                        (requested_network.network_id,
                         str(requested_network.address)))
        if 'host_param' in expected_kwargs:
            expected_kwargs['host'] = expected_kwargs.pop('host_param')
        else:
            expected_kwargs.pop('host', None)
        if 'legacy_limits' in expected_kwargs:
            expected_kwargs['limits'] = expected_kwargs.pop('legacy_limits')
            kwargs.pop('legacy_limits', None)
        expected_kwargs.pop('destination', None)

        if 'mountpoint' in expected_kwargs and expected_version == '4.0':
            # TODO(danms): Remove me when we drop 3.x
            del expected_kwargs['mountpoint']
            del expected_kwargs['volume_id']

        if assert_dict:
            expected_kwargs['instance'] = jsonutils.to_primitive(
                expected_kwargs['instance'])

        cast_and_call = ['confirm_resize', 'stop_instance']
        if rpc_method == 'call' and method in cast_and_call:
            if method == 'confirm_resize':
                kwargs['cast'] = False
            else:
                kwargs['do_cast'] = False
        if 'host' in kwargs:
            host = kwargs['host']
        elif 'destination' in kwargs:
            host = kwargs['destination']
        elif 'instances' in kwargs:
            host = kwargs['instances'][0]['host']
        else:
            host = kwargs['instance']['host']

        with contextlib.nested(
            mock.patch.object(rpcapi.client, rpc_method),
            mock.patch.object(rpcapi.client, 'prepare'),
            mock.patch.object(rpcapi.client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):
            prepare_mock.return_value = rpcapi.client
            if '_return_value' in kwargs:
                rpc_mock.return_value = kwargs.pop('_return_value')
                del expected_kwargs['_return_value']
            elif 'return_bdm_object' in kwargs:
                del kwargs['return_bdm_object']
                rpc_mock.return_value = objects_block_dev.BlockDeviceMapping()
            elif rpc_method == 'call':
                rpc_mock.return_value = 'foo'
            else:
                rpc_mock.return_value = None
            csv_mock.side_effect = (
                lambda v: orig_prepare(version=v).can_send_version())

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, rpc_mock.return_value)

            prepare_mock.assert_called_once_with(version=expected_version,
                                                 server=host)
            rpc_mock.assert_called_once_with(ctxt, method, **expected_kwargs)

    def test_add_aggregate_host(self):
        self._test_compute_api('add_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('add_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={}, version='3.0')

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance_obj, network_id='id',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance_obj, network_id='id',
                version='3.12')

    def test_attach_interface(self):
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance_obj, network_id='id',
                port_id='id2', version='4.0', requested_ip='192.168.1.50')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance_obj, network_id='id',
                port_id='id2', version='3.17', requested_ip='192.168.1.50')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                mountpoint='mp', bdm=self.fake_volume_bdm, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                mountpoint='mp', bdm=self.fake_volume_bdm, version='3.16')

    def test_change_instance_metadata(self):
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance_obj, diff={}, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance_obj, diff={}, version='3.7')

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_check_can_live_migrate_destination(self, mock_warn):
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance_obj,
                destination='dest', block_migration=True,
                disk_over_commit=True, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance_obj,
                destination='dest', block_migration=True,
                disk_over_commit=True, version='3.32')
        self.assertFalse(mock_warn.called)

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_check_can_live_migrate_destination_old_warning(self, mock_warn):
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance_obj,
                destination='dest', block_migration=True,
                disk_over_commit=True, version='3.0')
        mock_warn.assert_called_once_with()

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_check_can_live_migrate_source(self, mock_warn):
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance_obj,
                dest_check_data={"test": "data"}, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance_obj,
                dest_check_data={"test": "data"}, version='3.32')
        self.assertFalse(mock_warn.called)

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_check_can_live_migrate_source_old_warning(self, mock_warn):
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance_obj,
                dest_check_data={"test": "data"}, version='3.0')
        mock_warn.assert_called_once_with()

    def test_check_instance_shared_storage(self):
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance_obj, data='foo',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance_obj, data='foo',
                version='3.29')

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

    def test_detach_interface(self):
        self._test_compute_api('detach_interface', 'cast',
                version='4.0', instance=self.fake_instance_obj,
                port_id='fake_id')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('detach_interface', 'cast',
                version='3.17', instance=self.fake_instance_obj,
                port_id='fake_id')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance_obj, volume_id='id',
                version='3.25')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                reservations=list('fake_res'))

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                reservations=list('fake_res'))

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance_obj, tail_length='tl',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance_obj, tail_length='tl',
                version='3.28')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

    def test_get_console_topic(self):
        self._test_compute_api('get_console_topic', 'call', host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_console_topic', 'call', host='host')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance_obj, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance_obj, version='3.18')

    def test_get_instance_diagnostics(self):
        self._test_compute_api('get_instance_diagnostics', 'call',
                assert_dict=True, instance=self.fake_instance_obj,
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_instance_diagnostics', 'call',
                assert_dict=True, instance=self.fake_instance_obj,
                version='3.31')

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='3.2')

    def test_get_spice_console(self):
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='3.1')

    def test_get_rdp_console(self):
        self._test_compute_api('get_rdp_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_rdp_console', 'call',
                instance=self.fake_instance_obj, console_type='type',
                version='3.10')

    def test_get_serial_console(self):
        self._test_compute_api('get_serial_console', 'call',
                instance=self.fake_instance_obj, console_type='serial',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_serial_console', 'call',
                instance=self.fake_instance_obj, console_type='serial',
                version='3.34')

    def test_validate_console_port(self):
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance_obj, port="5900",
                console_type="novnc", version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance_obj, port="5900",
                console_type="novnc", version='3.3')

    def test_host_maintenance_mode(self):
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

    def test_host_power_action(self):
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

    def test_inject_network_info(self):
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance_obj)

    def test_live_migration(self):
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance_obj, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migrate_data={}, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance_obj, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migrate_data={}, version='3.26')

    def test_post_live_migration_at_destination(self):
        self._test_compute_api('post_live_migration_at_destination', 'cast',
                instance=self.fake_instance_obj,
                block_migration='block_migration', host='host', version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('post_live_migration_at_destination', 'cast',
                instance=self.fake_instance_obj,
                block_migration='block_migration', host='host', version='3.14')

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_soft_delete_instance(self):
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance_obj,
                reservations=['uuid1', 'uuid2'])

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance_obj,
                reservations=['uuid1', 'uuid2'])

    def test_swap_volume(self):
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance_obj, old_volume_id='oldid',
                new_volume_id='newid')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance_obj, old_volume_id='oldid',
                new_volume_id='newid')

    def test_restore_instance(self):
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance_obj, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance_obj, version='3.20')

    def test_pre_live_migration(self):
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance_obj,
                block_migration='block_migration', disk='disk', host='host',
                migrate_data=None, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance_obj,
                block_migration='block_migration', disk='disk', host='host',
                migrate_data=None, version='3.19')

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node', clean_shutdown=True, version='4.0')

        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node', version='3.0')
        self.flags(compute='3.38', group='upgrade_levels')
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node', clean_shutdown=True, version='3.38')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance_obj, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node', clean_shutdown=True, version='3.38')

    def test_reboot_instance(self):
        self.maxDiff = None
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance_obj,
                block_device_info={},
                reboot_type='type')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance_obj,
                block_device_info={},
                reboot_type='type')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance_obj, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                preserve_ephemeral=True, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance_obj, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                preserve_ephemeral=True, version='3.21')

    def test_reserve_block_device_name(self):
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance_obj, device='device',
                volume_id='id', disk_bus='ide', device_type='cdrom',
                version='4.0',
                _return_value=objects_block_dev.BlockDeviceMapping())

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance_obj, device='device',
                volume_id='id', disk_bus='ide', device_type='cdrom',
                version='3.35', return_bdm_object=True)

    def refresh_provider_fw_rules(self):
        self._test_compute_api('refresh_provider_fw_rules', 'cast',
                host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('refresh_provider_fw_rules', 'cast',
                host='host')

    def test_refresh_security_group_rules(self):
        self._test_compute_api('refresh_security_group_rules', 'cast',
                security_group_id='id', host='host', version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('refresh_security_group_rules', 'cast',
                security_group_id='id', host='host', version='3.0')

    def test_refresh_security_group_members(self):
        self._test_compute_api('refresh_security_group_members', 'cast',
                security_group_id='id', host='host', version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('refresh_security_group_members', 'cast',
                security_group_id='id', host='host', version='3.0')

    def test_refresh_instance_security_rules(self):
        self._test_compute_api('refresh_instance_security_rules', 'cast',
                host='fake_host', instance=self.fake_instance_obj,
                version='4.0', assert_dict=True)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('refresh_instance_security_rules', 'cast',
                host='fake_host', instance=self.fake_instance_obj,
                version='3.0', assert_dict=True)

    def test_remove_aggregate_host(self):
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance_obj, address='addr',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance_obj, address='addr',
                version='3.13')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host',
                version='3.30')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref',
            clean_shutdown=True, version='4.0')
        self.flags(compute='3.9', group='upgrade_levels')
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            version='3.9')
        self.flags(compute='3.24', group='upgrade_levels')
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref', version='3.24')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref',
            clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('rescue_instance', 'cast',
            instance=self.fake_instance_obj, rescue_password='pw',
            rescue_image_ref='fake_image_ref',
            clean_shutdown=True, version='3.37')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance_obj)

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'),
                clean_shutdown=True, version='4.0')
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'), version='3.0')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'),
                clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'),
                clean_shutdown=True, version='3.37')

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance_obj, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_rollback_live_migration_at_destination(self, mock_warn):
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance_obj, host='host',
                destroy_disks=True, migrate_data=None, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance_obj, host='host',
                destroy_disks=True, migrate_data=None, version='3.32')
        self.assertFalse(mock_warn.called)

    @mock.patch('nova.compute.rpcapi.ComputeAPI._warn_buggy_live_migrations')
    def test_rollback_live_migration_at_destination_old_warning(self,
                                                                mock_warn):
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance_obj, host='host',
                version='3.0')
        mock_warn.assert_called_once_with(None)

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance_obj, new_pass='pw',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance_obj, new_pass='pw',
                version='3.8')

    def test_set_host_enabled(self):
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

    def test_get_host_uptime(self):
        self._test_compute_api('get_host_uptime', 'call', host='host')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('get_host_uptime', 'call', host='host')

    def test_backup_instance(self):
        self._test_compute_api('backup_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id',
                backup_type='type', rotation='rotation')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('backup_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id',
                backup_type='type', rotation='rotation')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance_obj, image_id='id')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance_obj)

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='4.0')
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance_obj, version='3.0')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='4.0')
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj, version='3.0')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance_obj, bdms=[],
                reservations=['uuid1', 'uuid2'], version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance_obj, bdms=[],
                reservations=['uuid1', 'uuid2'], version='3.22')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance_obj)

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance_obj)

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance_obj, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance_obj, version='3.11')

    def test_shelve_instance(self):
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                clean_shutdown=True, version='4.0')
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                version='3.0')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance_obj, image_id='image_id',
                clean_shutdown=True, version='3.37')

    def test_shelve_offload_instance(self):
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='4.0')
        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                version='3.0')
        self.flags(compute='3.37', group='upgrade_levels')
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')
        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance_obj,
                clean_shutdown=True, version='3.37')

    def test_unshelve_instance(self):
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                filter_properties={'fakeprop': 'fakeval'}, node='node',
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                filter_properties={'fakeprop': 'fakeval'}, node='node',
                version='3.15')

    def test_volume_snapshot_create(self):
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                create_info={}, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                create_info={}, version='3.6')

    def test_volume_snapshot_delete(self):
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance_obj, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='3.6')

    def test_external_instance_event(self):
        self._test_compute_api('external_instance_event', 'cast',
                               instances=[self.fake_instance_obj],
                               events=['event'],
                               version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('external_instance_event', 'cast',
                               instances=[self.fake_instance_obj],
                               events=['event'],
                               version='3.23')

    def test_build_and_run_instance(self):
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks=['network1'], security_groups=None,
                block_device_mapping=None, node='node', limits=[],
                version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks=['network1'], security_groups=None,
                block_device_mapping=None, node='node', limits=[],
                version='3.40')

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_build_and_run_instance_icehouse_compat(self, is_neutron):
        self.flags(compute='icehouse', group='upgrade_levels')
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks= objects_network_request.NetworkRequestList(
                    objects=[objects_network_request.NetworkRequest(
                        network_id="fake_network_id", address="10.0.0.1",
                        port_id="fake_port_id")]),
                security_groups=None,
                block_device_mapping=None, node='node', limits={},
                version='3.23')

    @mock.patch('nova.utils.is_neutron', return_value=False)
    def test_build_and_run_instance_icehouse_compat_nova_net(self, is_neutron):
        self.flags(compute='icehouse', group='upgrade_levels')
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks= objects_network_request.NetworkRequestList(
                    objects=[objects_network_request.NetworkRequest(
                        network_id='fake_network_id', address='10.0.0.1')]),
                security_groups=None,
                block_device_mapping=None, node='node', limits={},
                version='3.23', nova_network=True)

    def test_quiesce_instance(self):
        self._test_compute_api('quiesce_instance', 'call',
                instance=self.fake_instance_obj, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('quiesce_instance', 'call',
                instance=self.fake_instance_obj, version='3.39')

    def test_unquiesce_instance(self):
        self._test_compute_api('unquiesce_instance', 'cast',
                instance=self.fake_instance_obj, mapping=None, version='4.0')

        self.flags(compute='kilo', group='upgrade_levels')
        self._test_compute_api('unquiesce_instance', 'cast',
                instance=self.fake_instance_obj, mapping=None, version='3.39')

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_build_and_run_instance_juno_compat(self, is_neutron):
        self.flags(compute='juno', group='upgrade_levels')
        self._test_compute_api('build_and_run_instance', 'cast',
                instance=self.fake_instance_obj, host='host', image='image',
                request_spec={'request': 'spec'}, filter_properties=[],
                admin_password='passwd', injected_files=None,
                requested_networks= objects_network_request.NetworkRequestList(
                    objects=[objects_network_request.NetworkRequest(
                        network_id="fake_network_id", address="10.0.0.1",
                        port_id="fake_port_id")]),
                security_groups=None,
                block_device_mapping=None, node='node', limits={},
                version='3.33')

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_build_and_run_instance_limits_juno_compat(
            self, is_neutron, get_by_host_and_nodename):
        host_topology = objects_numa.NUMATopology(cells=[
            objects_numa.NUMACell(
                id=0, cpuset=set([1, 2]), memory=512,
                cpu_usage=2, memory_usage=256,
                pinned_cpus=set([1])),
            objects_numa.NUMACell(
                id=1, cpuset=set([3, 4]), memory=512,
                cpu_usage=1, memory_usage=128,
                pinned_cpus=set([]))
        ])
        limits = objects_numa.NUMATopologyLimits(
            cpu_allocation_ratio=16,
            ram_allocation_ratio=2)
        cnode = objects_compute_node.ComputeNode(
            numa_topology=jsonutils.dumps(
                host_topology.obj_to_primitive()))

        get_by_host_and_nodename.return_value = cnode
        legacy_limits = jsonutils.dumps(
            limits.to_dict_legacy(host_topology))

        self.flags(compute='juno', group='upgrade_levels')
        netreqs = objects_network_request.NetworkRequestList(objects=[
            objects_network_request.NetworkRequest(
                network_id="fake_network_id",
                address="10.0.0.1",
                port_id="fake_port_id")])

        self._test_compute_api('build_and_run_instance', 'cast',
                               instance=self.fake_instance_obj,
                               host='host',
                               image='image',
                               request_spec={'request': 'spec'},
                               filter_properties=[],
                               admin_password='passwd',
                               injected_files=None,
                               requested_networks=netreqs,
                               security_groups=None,
                               block_device_mapping=None,
                               node='node',
                               limits={'numa_topology': limits},
                               legacy_limits={'numa_topology': legacy_limits},
                               version='3.33')
