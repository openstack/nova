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

from nova import context
from nova import flags
from nova.openstack.common import rpc
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test


FLAGS = flags.FLAGS


class SchedulerRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(SchedulerRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(SchedulerRpcAPITestCase, self).tearDown()

    def _test_scheduler_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        expected_retval = 'foo' if method == 'call' else None
        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        expected_msg['version'] = expected_version
        if rpc_method == 'cast' and method == 'run_instance':
            kwargs['call'] = False

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
        expected_args = [ctxt, FLAGS.scheduler_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_run_instance_call(self):
        self._test_scheduler_api('run_instance', rpc_method='call',
                request_spec='fake_request_spec',
                admin_password='pw', injected_files='fake_injected_files',
                requested_networks='fake_requested_networks',
                is_first_time=True, filter_properties='fake_filter_properties',
                reservations=None, version='1.2')

    def test_run_instance_cast(self):
        self._test_scheduler_api('run_instance', rpc_method='cast',
                request_spec='fake_request_spec',
                admin_password='pw', injected_files='fake_injected_files',
                requested_networks='fake_requested_networks',
                is_first_time=True, filter_properties='fake_filter_properties',
                reservations=None, version='1.2')

    def test_prep_resize(self):
        self._test_scheduler_api('prep_resize', rpc_method='cast',
                instance='fake_instance',
                instance_type='fake_type', image='fake_image',
                update_db='fake_update_db', request_spec='fake_request_spec',
                filter_properties='fake_props', version='1.1')

    def test_show_host_resources(self):
        self._test_scheduler_api('show_host_resources', rpc_method='call',
                host='fake_host')

    def test_live_migration(self):
        self._test_scheduler_api('live_migration', rpc_method='call',
                block_migration='fake_block_migration',
                disk_over_commit='fake_disk_over_commit',
                instance_id='fake_id', dest='fake_dest', topic='fake_topic')

    def test_update_service_capabilities(self):
        self._test_scheduler_api('update_service_capabilities',
                rpc_method='fanout_cast', service_name='fake_name',
                host='fake_host', capabilities='fake_capabilities')
