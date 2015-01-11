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

        rpc_method(ctxt, method, **expected_kwargs).AndReturn('foo')

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
