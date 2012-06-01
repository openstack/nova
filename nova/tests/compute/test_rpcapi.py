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
from nova import flags
from nova import rpc
from nova import test


FLAGS = flags.FLAGS


class ComputeRpcAPITestCase(test.TestCase):

    def setUp(self):
        self.fake_instance = {'uuid': 'fake_uuid', 'host': 'fake_host'}
        super(ComputeRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(ComputeRpcAPITestCase, self).tearDown()

    def _test_compute_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = compute_rpcapi.ComputeAPI()
        expected_retval = 'foo' if method == 'call' else None
        expected_msg = rpcapi.make_msg(method, **kwargs)
        if 'host_param' in expected_msg['args']:
            host_param = expected_msg['args']['host_param']
            del expected_msg['args']['host_param']
            expected_msg['args']['host'] = host_param
        elif 'host' in expected_msg['args']:
            del expected_msg['args']['host']
        if 'instance' in expected_msg['args']:
            instance = expected_msg['args']['instance']
            del expected_msg['args']['instance']
            expected_msg['args']['instance_uuid'] = instance['uuid']
        expected_msg['version'] = rpcapi.RPC_API_VERSION
        cast_and_call = ['confirm_resize', 'stop_instance']
        if rpc_method == 'call' and method in cast_and_call:
            kwargs['cast'] = False
        if 'host' in kwargs:
            host = kwargs['host']
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
                instance=self.fake_instance, network_id='id')

    def test_attach_volume(self):
        self._test_compute_api('attach_volume', 'cast',
                instance=self.fake_instance, volume_id='id', mountpoint='mp')

    def test_confirm_resize_cast(self):
        self._test_compute_api('confirm_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host')

    def test_confirm_resize_call(self):
        self._test_compute_api('confirm_resize', 'call',
                instance=self.fake_instance, migration_id='id', host='host')

    def test_detach_volume(self):
        self._test_compute_api('detach_volume', 'cast',
                instance=self.fake_instance, volume_id='id')

    def test_finish_revert_resize(self):
        self._test_compute_api('finish_revert_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host')

    def test_get_console_output(self):
        self._test_compute_api('get_console_output', 'call',
                instance=self.fake_instance, tail_length='tl')

    def test_get_console_pool_info(self):
        self._test_compute_api('get_console_pool_info', 'call',
                console_type='type', host='host')

    def test_get_diagnostics(self):
        self._test_compute_api('get_diagnostics', 'call',
                instance=self.fake_instance)

    def test_get_vnc_console(self):
        self._test_compute_api('get_vnc_console', 'call',
                instance=self.fake_instance, console_type='type')

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

    def test_lock_instance(self):
        self._test_compute_api('lock_instance', 'cast',
                instance=self.fake_instance)

    def test_pause_instance(self):
        self._test_compute_api('pause_instance', 'cast',
                instance=self.fake_instance)

    def test_power_off_instance(self):
        self._test_compute_api('power_off_instance', 'cast',
                instance=self.fake_instance)

    def test_power_on_instance(self):
        self._test_compute_api('power_on_instance', 'cast',
                instance=self.fake_instance)

    def test_reboot_instance(self):
        self._test_compute_api('reboot_instance', 'cast',
                instance=self.fake_instance, reboot_type='type')

    def test_rebuild_instance(self):
        self._test_compute_api('rebuild_instance', 'cast',
                instance=self.fake_instance, new_pass='pass',
                injected_files='files', image_ref='ref',
                orig_image_ref='orig_ref')

    def test_refresh_security_group_rules(self):
        self._test_compute_api('refresh_security_group_rules', 'cast',
                security_group_id='id', host='host')

    def test_refresh_security_group_members(self):
        self._test_compute_api('refresh_security_group_members', 'cast',
                security_group_id='id', host='host')

    def test_remove_aggregate_host(self):
        self._test_compute_api('remove_aggregate_host', 'cast',
                aggregate_id='id', host_param='host', host='host')

    def test_remove_fixed_ip_from_instance(self):
        self._test_compute_api('remove_fixed_ip_from_instance', 'cast',
                instance=self.fake_instance, address='addr')

    def test_rescue_instance(self):
        self._test_compute_api('rescue_instance', 'cast',
                instance=self.fake_instance, rescue_password='pw')

    def test_reset_network(self):
        self._test_compute_api('reset_network', 'cast',
                instance=self.fake_instance)

    def test_resize_instance(self):
        self._test_compute_api('resize_instance', 'cast',
                instance=self.fake_instance, migration_id='id', image='image')

    def test_resume_instance(self):
        self._test_compute_api('resume_instance', 'cast',
                instance=self.fake_instance)

    def test_revert_resize(self):
        self._test_compute_api('revert_resize', 'cast',
                instance=self.fake_instance, migration_id='id', host='host')

    def test_set_admin_password(self):
        self._test_compute_api('set_admin_password', 'cast',
                instance=self.fake_instance, new_pass='pw')

    def test_set_host_enabled(self):
        self._test_compute_api('set_host_enabled', 'call',
                enabled='enabled', host='host')

    def test_snapshot_instance(self):
        self._test_compute_api('snapshot_instance', 'cast',
                instance=self.fake_instance, image_id='id', image_type='type',
                backup_type='type', rotation='rotation')

    def test_start_instance(self):
        self._test_compute_api('start_instance', 'cast',
                instance=self.fake_instance)

    def test_stop_instance_cast(self):
        self._test_compute_api('stop_instance', 'cast',
                instance=self.fake_instance)

    def test_stop_instance_call(self):
        self._test_compute_api('stop_instance', 'call',
                instance=self.fake_instance)

    def test_suspend_instance(self):
        self._test_compute_api('suspend_instance', 'cast',
                instance=self.fake_instance)

    def test_terminate_instance(self):
        self._test_compute_api('terminate_instance', 'cast',
                instance=self.fake_instance)

    def test_unlock_instance(self):
        self._test_compute_api('unlock_instance', 'cast',
                instance=self.fake_instance)

    def test_unpause_instance(self):
        self._test_compute_api('unpause_instance', 'cast',
                instance=self.fake_instance)

    def test_unrescue_instance(self):
        self._test_compute_api('unrescue_instance', 'cast',
                instance=self.fake_instance)
