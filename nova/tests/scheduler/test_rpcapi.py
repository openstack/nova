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
Unit Tests for nova.scheduler.rpcapi
"""

from oslo.config import cfg

from nova import context
from nova.openstack.common import rpc
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test

CONF = cfg.CONF


class SchedulerRpcAPITestCase(test.NoDBTestCase):
    def _test_scheduler_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        expected_retval = 'foo' if method == 'call' else None
        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        expected_msg['version'] = expected_version

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
        expected_args = [ctxt, CONF.scheduler_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_run_instance(self):
        self._test_scheduler_api('run_instance', rpc_method='cast',
                request_spec='fake_request_spec',
                admin_password='pw', injected_files='fake_injected_files',
                requested_networks='fake_requested_networks',
                is_first_time=True, filter_properties='fake_filter_properties',
                legacy_bdm_in_spec=False, version='2.9')

    def test_prep_resize(self):
        self._test_scheduler_api('prep_resize', rpc_method='cast',
                instance='fake_instance',
                instance_type='fake_type', image='fake_image',
                request_spec='fake_request_spec',
                filter_properties='fake_props', reservations=list('fake_res'))

    def test_live_migration(self):
        self._test_scheduler_api('live_migration', rpc_method='call',
                block_migration='fake_block_migration',
                disk_over_commit='fake_disk_over_commit',
                instance='fake_instance', dest='fake_dest')

    def test_update_service_capabilities(self):
        self._test_scheduler_api('update_service_capabilities',
                rpc_method='fanout_cast', service_name='fake_name',
                host='fake_host', capabilities='fake_capabilities',
                version='2.4')

    def test_select_hosts(self):
        self._test_scheduler_api('select_hosts', rpc_method='call',
                request_spec='fake_request_spec',
                filter_properties='fake_prop',
                version='2.6')

    def test_select_destinations(self):
        self._test_scheduler_api('select_destinations', rpc_method='call',
                request_spec='fake_request_spec',
                filter_properties='fake_prop',
                version='2.7')
