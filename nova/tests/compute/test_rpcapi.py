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
from oslo.config import cfg

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import db
from nova.openstack.common import jsonutils
from nova import test
from nova.tests import fake_block_device

CONF = cfg.CONF


class ComputeRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(ComputeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        inst = db.instance_create(self.context, {'host': 'fake_host',
                                                 'instance_type_id': 1})
        self.fake_instance = jsonutils.to_primitive(inst)
        self.fake_volume_bdm = jsonutils.to_primitive(
                fake_block_device.FakeDbBlockDeviceDict(
                    {'source_type': 'volume', 'destination_type': 'volume',
                     'instance_uuid': self.fake_instance['uuid'],
                     'volume_id': 'fake-volume-id'}))

    def test_serialized_instance_has_name(self):
        self.assertIn('name', self.fake_instance)

    def _test_compute_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = kwargs.pop('rpcapi_class', compute_rpcapi.ComputeAPI)()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic, CONF.compute_topic)

        orig_prepare = rpcapi.client.prepare
        expected_version = kwargs.pop('version', rpcapi.client.target.version)

        expected_kwargs = kwargs.copy()
        if 'host_param' in expected_kwargs:
            expected_kwargs['host'] = expected_kwargs.pop('host_param')
        else:
            expected_kwargs.pop('host', None)
        expected_kwargs.pop('destination', None)

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
            rpc_mock.return_value = 'foo' if rpc_method == 'call' else None
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

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('add_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={}, version='2.14')

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance, network_id='id', version='3.12')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance, network_id='id', version='2.0')

    def test_attach_interface(self):
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance, network_id='id', port_id='id2',
                version='3.17', requested_ip='192.168.1.50')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('attach_interface', 'call',
                instance=self.fake_instance, network_id='id', port_id='id2',
                requested_ip='192.168.1.50', version='2.25')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', mountpoint='mp',
                bdm=self.fake_volume_bdm, version='3.16')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', mountpoint='mp',
                version='2.0')

    def test_change_instance_metadata(self):
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance, diff={}, version='3.7')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance, diff={}, version='2.0')

    def test_check_can_live_migrate_destination(self):
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance,
                destination='dest', block_migration=True,
                disk_over_commit=True)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance,
                destination='dest', block_migration=True,
                disk_over_commit=True, version='2.38')

    def test_check_can_live_migrate_source(self):
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance,
                dest_check_data={"test": "data"})

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance,
                dest_check_data={"test": "data"}, version='2.38')

    def test_check_instance_shared_storage(self):
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance, data='foo')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance, data='foo', version='2.28')

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'), version='2.39')

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'), version='2.39')

    def test_detach_interface(self):
        self._test_compute_api('detach_interface', 'cast',
                version='3.17', instance=self.fake_instance, port_id='fake_id')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('detach_interface', 'cast',
                instance=self.fake_instance, port_id='fake_id', version='2.25')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance, volume_id='id')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', version='2.0')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                reservations=list('fake_res'), version='2.46')

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'), version='2.47')

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance, tail_length='tl')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance, tail_length='tl', version='2.0')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host', version='2.0')

    def test_get_console_topic(self):
        self._test_compute_api('get_console_topic', 'call', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_console_topic', 'call', host='host',
                version='2.0')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance, version='3.18')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance, version='2.0')

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='3.2')

        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='3.0')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='2.0')

    def test_get_spice_console(self):
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='3.1')

        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='3.0')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='2.24')

    def test_get_rdp_console(self):
        self._test_compute_api('get_rdp_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='3.10')

    def test_validate_console_port(self):
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance, port="5900",
                console_type="novnc", version='3.3')

        self.flags(compute='3.0', group='upgrade_levels')
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance, port="5900",
                console_type="novnc", version='3.0')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance, port="5900",
                console_type="novnc", version='2.26')

    def test_host_maintenance_mode(self):
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host', version='2.0')

    def test_host_power_action(self):
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host', version='2.0')

    def test_inject_network_info(self):
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance, version='2.41')

    def test_live_migration(self):
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migrate_data={})

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migrate_data={}, version='2.0')

    def test_post_live_migration_at_destination(self):
        self._test_compute_api('post_live_migration_at_destination', 'cast',
                instance=self.fake_instance, block_migration='block_migration',
                host='host', version='3.14')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('post_live_migration_at_destination', 'cast',
                instance=self.fake_instance, block_migration='block_migration',
                host='host', version='2.0')

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance, version='2.36')

    def test_soft_delete_instance(self):
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance,
                reservations=['uuid1', 'uuid2'])

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance,
                reservations=['uuid1', 'uuid2'], version='2.35')

    def test_swap_volume(self):
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance, old_volume_id='oldid',
                new_volume_id='newid')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance, old_volume_id='oldid',
                new_volume_id='newid', version='2.34')

    def test_restore_instance(self):
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance, version='3.20')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance, version='2.0')

    def test_pre_live_migration(self):
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                disk='disk', host='host', migrate_data=None, version='3.19')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                disk='disk', host='host', migrate_data=None, version='2.21')

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node', version='2.43')

    def test_reboot_instance(self):
        self.maxDiff = None
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance,
                block_device_info={},
                reboot_type='type')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance,
                block_device_info={},
                reboot_type='type', version='2.32')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                preserve_ephemeral=True, version='3.21')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                version='2.22')

    def test_rebuild_instance_preserve_ephemeral(self):
        self.flags(compute='3.5', group='upgrade_levels')
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                preserve_ephemeral=True, version='3.5')

    def test_reserve_block_device_name(self):
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance, device='device', volume_id='id',
                disk_bus='ide', device_type='cdrom', version='3.16')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance, device='device', volume_id='id',
                version='2.3')

    def refresh_provider_fw_rules(self):
        self._test_compute_api('refresh_provider_fw_rules', 'cast',
                host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('refresh_provider_fw_rules', 'cast',
                host='host', version='2.0')

    def test_refresh_security_group_rules(self):
        self._test_compute_api('refresh_security_group_rules', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('refresh_security_group_rules', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host', version='2.0')

    def test_refresh_security_group_members(self):
        self._test_compute_api('refresh_security_group_members', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('refresh_security_group_members', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host', version='2.0')

    def test_remove_aggregate_host(self):
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={})

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={}, version='2.15')

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance, address='addr',
                version='3.13')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance, address='addr', version='2.0')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host',
                version='2.0')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
                instance=self.fake_instance, rescue_password='pw',
                version='3.9')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('rescue_instance', 'cast',
                instance=self.fake_instance, rescue_password='pw',
                version='2.44')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance, version='2.40')

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'), version='2.45')

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance, version='2.33')

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'))

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'), version='2.39')

    def test_rollback_live_migration_at_destination(self):
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance, host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance, host='host',
                version='2.0')

    def test_run_instance(self):
        self._test_compute_api('run_instance', 'cast',
                instance=self.fake_instance, host='fake_host',
                request_spec='fake_spec', filter_properties={},
                requested_networks='networks', injected_files='files',
                admin_password='pw', is_first_time=True, node='node',
                legacy_bdm_in_spec=False)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('run_instance', 'cast',
                instance=self.fake_instance, host='fake_host',
                request_spec='fake_spec', filter_properties={},
                requested_networks='networks', injected_files='files',
                admin_password='pw', is_first_time=True, node='node',
                legacy_bdm_in_spec=False, version='2.37')

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance, new_pass='pw',
                version='3.8')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance, new_pass='pw', version='2.0')

    def test_set_host_enabled(self):
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host', version='2.0')

    def test_get_host_uptime(self):
        self._test_compute_api('get_host_uptime', 'call', host='host')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('get_host_uptime', 'call', host='host',
                version='2.0')

    def test_backup_instance(self):
        self._test_compute_api('backup_instance', 'cast',
                instance=self.fake_instance, image_id='id',
                backup_type='type', rotation='rotation')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('backup_instance', 'cast',
                instance=self.fake_instance, image_id='id',
                backup_type='type', rotation='rotation', version='2.42')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id', version='2.42')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance, version='2.29')

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance, version='2.29')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance, version='2.29')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance, version='2.33')

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance, bdms=[],
                reservations=['uuid1', 'uuid2'], version='3.22')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance, bdms=[],
                reservations=['uuid1', 'uuid2'], version='2.35')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance, version='2.36')

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance, version='3.11')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance, version='2.0')

    def test_shelve_instance(self):
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance, image_id='image_id')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance, image_id='image_id',
                version='2.31')

    def test_shelve_offload_instance(self):
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance)

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance, version='2.31')

    def test_unshelve_instance(self):
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance, host='host', image='image',
                filter_properties={'fakeprop': 'fakeval'}, node='node',
                version='3.15')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance, host='host', image='image',
                version='2.31')

    def test_volume_snapshot_create(self):
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance, volume_id='fake_id',
                create_info={}, version='3.6')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('volume_snapshot_create', 'cast',
                instance=self.fake_instance, volume_id='fake_id',
                create_info={}, version='2.44')

    def test_volume_snapshot_delete(self):
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='3.6')

        # NOTE(russellb) Havana compat
        self.flags(compute='havana', group='upgrade_levels')
        self._test_compute_api('volume_snapshot_delete', 'cast',
                instance=self.fake_instance, volume_id='fake_id',
                snapshot_id='fake_id2', delete_info={}, version='2.44')
