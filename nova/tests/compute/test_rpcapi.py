# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import db
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
from nova import test

CONF = cfg.CONF


class ComputeRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(ComputeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        inst = db.instance_create(self.context, {'host': 'fake_host',
                                                 'instance_type_id': 1})
        self.fake_instance = jsonutils.to_primitive(inst)

    def test_serialized_instance_has_name(self):
        self.assertTrue('name' in self.fake_instance)

    def _test_compute_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        if 'rpcapi_class' in kwargs:
            rpcapi_class = kwargs['rpcapi_class']
            del kwargs['rpcapi_class']
        else:
            rpcapi_class = compute_rpcapi.ComputeAPI
        rpcapi = rpcapi_class()
        expected_retval = 'foo' if method == 'call' else None

        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        if 'host_param' in expected_msg['args']:
            host_param = expected_msg['args']['host_param']
            del expected_msg['args']['host_param']
            expected_msg['args']['host'] = host_param
        elif 'host' in expected_msg['args']:
            del expected_msg['args']['host']
        if 'destination' in expected_msg['args']:
            del expected_msg['args']['destination']
        expected_msg['version'] = expected_version

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
        expected_topic = '%s.%s' % (CONF.compute_topic, host)

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_add_aggregate_host(self):
        self._test_compute_api('add_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={}, version='2.14')

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance, network_id='id')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', mountpoint='mp')

    def test_change_instance_metadata(self):
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance, diff={})

    def test_check_can_live_migrate_destination(self):
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                instance=self.fake_instance,
                destination='dest', block_migration=True,
                disk_over_commit=True)

    def test_check_can_live_migrate_source(self):
        self._test_compute_api('check_can_live_migrate_source', 'call',
                instance=self.fake_instance,
                dest_check_data={"test": "data"})

    def test_check_instance_shared_storage(self):
        self._test_compute_api('check_instance_shared_storage', 'call',
                instance=self.fake_instance, data='foo', version='2.28')

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'), version='2.7')

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance, migration={'id': 'foo'},
                host='host', reservations=list('fake_res'), version='2.7')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance, volume_id='id')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'foo'},
                image='image', disk_info='disk_info', host='host',
                reservations=list('fake_res'), version='2.8')

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'), version='2.13')

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance, tail_length='tl')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

    def test_get_console_topic(self):
        self._test_compute_api('get_console_topic', 'call', host='host')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance)

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type')

    def test_get_spice_console(self):
        self._test_compute_api('get_spice_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='2.24')

    def test_validate_console_port(self):
        self._test_compute_api('validate_console_port', 'call',
                instance=self.fake_instance, port="5900",
                console_type="novnc",
                version="2.26")

    def test_host_maintenance_mode(self):
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

    def test_host_power_action(self):
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

    def test_inject_file(self):
        self._test_compute_api('inject_file', 'cast',
                instance=self.fake_instance, path='path', file_contents='fc')

    def test_inject_network_info(self):
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance)

    def test_live_migration(self):
        self._test_compute_api('live_migration', 'cast',
                instance=self.fake_instance, dest='dest',
                block_migration='blockity_block', host='tsoh',
                migrate_data={})

    def test_post_live_migration_at_destination(self):
        self._test_compute_api('post_live_migration_at_destination', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                host='host')

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                               instance=self.fake_instance, version='2.36')

    def test_power_off_instance(self):
        self._test_compute_api('power_off_instance', 'cast',
                instance=self.fake_instance)

    def test_power_on_instance(self):
        self._test_compute_api('power_on_instance', 'cast',
                instance=self.fake_instance)

    def test_soft_delete_instance(self):
        self._test_compute_api('soft_delete_instance', 'cast',
                instance=self.fake_instance,
                reservations=['uuid1', 'uuid2'],
                version='2.35')

    def test_swap_volume(self):
        self._test_compute_api('swap_volume', 'cast',
                instance=self.fake_instance, old_volume_id='oldid',
                new_volume_id='newid',
                version='2.34')

    def test_restore_instance(self):
        self._test_compute_api('restore_instance', 'cast',
                instance=self.fake_instance)

    def test_pre_live_migration(self):
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                disk='disk', host='host', migrate_data=None,
                version='2.21')

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance, instance_type='fake_type',
                image='fake_image', host='host',
                reservations=list('fake_res'),
                request_spec='fake_spec',
                filter_properties={'fakeprop': 'fakeval'},
                node='node',
                version='2.20')

    def test_reboot_instance(self):
        self.maxDiff = None
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance,
                block_device_info={},
                reboot_type='type',
                version='2.32')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast',
                instance=self.fake_instance, new_pass='pass',
                injected_files='files', image_ref='ref',
                orig_image_ref='orig_ref', bdms=[], recreate=False,
                on_shared_storage=False, orig_sys_metadata='orig_sys_metadata',
                version='2.22')

    def test_rebuild_instance_with_shared(self):
        self._test_compute_api('rebuild_instance', 'cast', new_pass='None',
                injected_files='None', image_ref='None', orig_image_ref='None',
                bdms=[], instance=self.fake_instance, host='new_host',
                orig_sys_metadata=None, recreate=True, on_shared_storage=True,
                version='2.22')

    def test_reserve_block_device_name(self):
        self._test_compute_api('reserve_block_device_name', 'call',
                instance=self.fake_instance, device='device', volume_id='id',
                version='2.3')

    def refresh_provider_fw_rules(self):
        self._test_compute_api('refresh_provider_fw_rules', 'cast',
                host='host')

    def test_refresh_security_group_rules(self):
        self._test_compute_api('refresh_security_group_rules', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host')

    def test_refresh_security_group_members(self):
        self._test_compute_api('refresh_security_group_members', 'cast',
                rpcapi_class=compute_rpcapi.SecurityGroupAPI,
                security_group_id='id', host='host')

    def test_remove_aggregate_host(self):
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate={'id': 'fake_id'}, host_param='host', host='host',
                slave_info={}, version='2.15')

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance, address='addr')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
                instance=self.fake_instance, rescue_password='pw')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance)

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                image='image', instance_type={'id': 1},
                reservations=list('fake_res'), version='2.16')

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                               instance=self.fake_instance,
                               version='2.33')

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance, migration={'id': 'fake_id'},
                host='host', reservations=list('fake_res'), version='2.12')

    def test_rollback_live_migration_at_destination(self):
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance, host='host')

    def test_run_instance(self):
        self._test_compute_api('run_instance', 'cast',
                instance=self.fake_instance, host='fake_host',
                request_spec='fake_spec', filter_properties={},
                requested_networks='networks', injected_files='files',
                admin_password='pw', is_first_time=True, node='node',
                legacy_bdm_in_spec=False, version='2.37')

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance, new_pass='pw')

    def test_set_host_enabled(self):
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

    def test_get_host_uptime(self):
        self._test_compute_api('get_host_uptime', 'call', host='host')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id', image_type='type',
                backup_type='type', rotation='rotation')

    def test_live_snapshot_instance(self):
        self._test_compute_api('live_snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id', version='2.30')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance, version='2.29')

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance, version='2.29')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance, version='2.29')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                               instance=self.fake_instance,
                               version='2.33')

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance, bdms=[],
                reservations=['uuid1', 'uuid2'],
                version='2.35')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                               instance=self.fake_instance,
                               version='2.36')

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance)

    def test_shelve_instance(self):
        self._test_compute_api('shelve_instance', 'cast',
                instance=self.fake_instance, image_id='image_id',
                version='2.31')

    def test_shelve_offload_instance(self):
        self._test_compute_api('shelve_offload_instance', 'cast',
                instance=self.fake_instance, version='2.31')

    def test_unshelve_instance(self):
        self._test_compute_api('unshelve_instance', 'cast',
                instance=self.fake_instance, host='host', image='image',
                version='2.31')
