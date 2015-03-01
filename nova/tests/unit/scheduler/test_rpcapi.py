# Copyright 2013 Red Hat, Inc.
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

from mox3 import mox
from oslo_config import cfg

from nova import context
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test

CONF = cfg.CONF


class SchedulerRpcAPITestCase(test.NoDBTestCase):
    def _test_scheduler_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic, CONF.scheduler_topic)

        expected_retval = 'foo' if rpc_method == 'call' else None
        expected_version = kwargs.pop('version', None)
        expected_fanout = kwargs.pop('fanout', None)
        expected_kwargs = kwargs.copy()

        self.mox.StubOutWithMock(rpcapi, 'client')

        rpcapi.client.can_send_version(
            mox.IsA(str)).MultipleTimes().AndReturn(True)

        prepare_kwargs = {}
        if expected_fanout:
            prepare_kwargs['fanout'] = True
        if expected_version:
            prepare_kwargs['version'] = expected_version
        rpcapi.client.prepare(**prepare_kwargs).AndReturn(rpcapi.client)

        rpc_method = getattr(rpcapi.client, rpc_method)

        rpc_method(ctxt, method, **expected_kwargs).AndReturn(expected_retval)

        self.mox.ReplayAll()

        # NOTE(markmc): MultipleTimes() is OnceOrMore() not ZeroOrMore()
        rpcapi.client.can_send_version('I fool you mox')

        retval = getattr(rpcapi, method)(ctxt, **kwargs)
        self.assertEqual(retval, expected_retval)

    def test_select_destinations(self):
        self._test_scheduler_api('select_destinations', rpc_method='call',
                request_spec='fake_request_spec',
                filter_properties='fake_prop',
                version='4.0')

    def test_update_aggregates(self):
        self._test_scheduler_api('update_aggregates', rpc_method='cast',
                aggregates='aggregates',
                version='4.1',
                fanout=True)

    def test_delete_aggregate(self):
        self._test_scheduler_api('delete_aggregate', rpc_method='cast',
                aggregate='aggregate',
                version='4.1',
                fanout=True)

    def test_update_instance_info(self):
        self._test_scheduler_api('update_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_info='fake_instance',
                fanout=True,
                version='4.2')

    def test_delete_instance_info(self):
        self._test_scheduler_api('delete_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_uuid='fake_uuid',
                fanout=True,
                version='4.2')

    def test_sync_instance_info(self):
        self._test_scheduler_api('sync_instance_info', rpc_method='cast',
                host_name='fake_host',
                instance_uuids=['fake1', 'fake2'],
                fanout=True,
                version='4.2')
