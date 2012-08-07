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

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import db
from nova import flags
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
from nova import test


FLAGS = flags.FLAGS


class ComputeRpcAPITestCase(test.TestCase):

    def setUp(self):
        self.context = context.get_admin_context()
        inst = db.instance_create(self.context, {'host': 'fake_host',
                                                 'instance_type_id': 1})
        self.fake_instance = jsonutils.to_primitive(inst)
        super(ComputeRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(ComputeRpcAPITestCase, self).tearDown()

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
            kwargs['cast'] = False
        if 'host' in kwargs:
            host = kwargs['host']
        elif 'destination' in kwargs:
            host = kwargs['destination']
        else:
            host = kwargs['instance']['host']
        expected_topic = '%s.%s' % (FLAGS.compute_topic, host)

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
        self._test_compute_api('add_aggregate_host', 'cast', aggregate_id='id',
                host_param='host', host='host')

    def test_add_fixed_ip_to_instance(self):
        self._test_compute_api('add_fixed_ip_to_instance', 'cast',
                instance=self.fake_instance, network_id='id', version='1.8')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', mountpoint='mp',
                version='1.9')

    def test_change_instance_metadata(self):
        self._test_compute_api('change_instance_metadata', 'cast',
                instance=self.fake_instance, diff={},
                version='1.36')

    def test_check_can_live_migrate_destination(self):
        self._test_compute_api('check_can_live_migrate_destination', 'call',
                version='1.10', instance=self.fake_instance,
                destination='dest', block_migration=True,
                disk_over_commit=True)

    def test_check_can_live_migrate_source(self):
        self._test_compute_api('check_can_live_migrate_source', 'call',
                version='1.11', instance=self.fake_instance,
                dest_check_data={"test": "data"})

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host',
                version='1.12')

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance, migration_id='id', host='host',
                version='1.12')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', version='1.13')

    def test_finish_resize(self):
        self._test_compute_api('finish_resize', 'cast',
                instance=self.fake_instance, migration_id='id',
                image='image', disk_info='disk_info', host='host',
                version='1.14')

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host',
                version='1.15')

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance, tail_length='tl', version='1.7')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

    def test_get_console_topic(self):
        self._test_compute_api('get_console_topic', 'call', host='host')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance, version='1.16')

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type',
                version='1.17')

    def test_host_maintenance_mode(self):
        self._test_compute_api('host_maintenance_mode', 'call',
                host_param='param', mode='mode', host='host')

    def test_host_power_action(self):
        self._test_compute_api('host_power_action', 'call', action='action',
                host='host')

    def test_inject_file(self):
        self._test_compute_api('inject_file', 'cast',
                instance=self.fake_instance, path='path', file_contents='fc',
                version='1.18')

    def test_inject_network_info(self):
        self._test_compute_api('inject_network_info', 'cast',
                instance=self.fake_instance, version='1.19')

    def test_post_live_migration_at_destination(self):
        self._test_compute_api('post_live_migration_at_destination', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                host='host', version='1.20')

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                instance=self.fake_instance, version='1.5')

    def test_power_off_instance(self):
        self._test_compute_api('power_off_instance', 'cast',
                instance=self.fake_instance, version='1.21')

    def test_power_on_instance(self):
        self._test_compute_api('power_on_instance', 'cast',
                instance=self.fake_instance, version='1.22')

    def test_pre_live_migration(self):
        self._test_compute_api('pre_live_migration', 'call',
                instance=self.fake_instance, block_migration='block_migration',
                disk='disk', host='host', version='1.23')

    def test_prep_resize(self):
        self._test_compute_api('prep_resize', 'cast',
                instance=self.fake_instance, instance_type='fake_type',
                image='fake_image', host='host', version='1.38')

    def test_reboot_instance(self):
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance, reboot_type='type', version='1.4')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast',
                instance=self.fake_instance, new_pass='pass',
                injected_files='files', image_ref='ref',
                orig_image_ref='orig_ref', version='1.24')

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
                aggregate_id='id', host_param='host', host='host')

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance, address='addr', version='1.25')

    def test_remove_volume_connection(self):
        self._test_compute_api('remove_volume_connection', 'call',
                instance=self.fake_instance, volume_id='id', host='host',
                version='1.26')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
                instance=self.fake_instance, rescue_password='pw',
                version='1.27')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance, version='1.28')

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance, migration_id='id', image='image',
                version='1.29')

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                instance=self.fake_instance, version='1.30')

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host',
                version='1.31')

    def test_rollback_live_migration_at_destination(self):
        self._test_compute_api('rollback_live_migration_at_destination',
                'cast', instance=self.fake_instance, host='host',
                version='1.32')

    def test_run_instance(self):
        self._test_compute_api('run_instance', 'cast',
                instance=self.fake_instance, host='fake_host',
                request_spec='fake_spec', filter_properties={},
                requested_networks='networks', injected_files='files',
                admin_password='pw', is_first_time=True, version='1.39')

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'call',
                instance=self.fake_instance, new_pass='pw', version='1.33')

    def test_set_host_enabled(self):
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

    def test_get_host_uptime(self):
        self._test_compute_api('get_host_uptime', 'call', host='host',
                version='1.1')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id', image_type='type',
                backup_type='type', rotation='rotation',
                version='1.34')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance, version='1.22')

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance, version='1.21')

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance, version='1.21')

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                instance=self.fake_instance, version='1.6')

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance, version='1.37')

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                instance=self.fake_instance, version='1.5')

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance, version='1.35')
