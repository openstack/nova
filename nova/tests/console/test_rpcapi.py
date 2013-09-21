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
Unit Tests for nova.console.rpcapi
"""

from oslo.config import cfg

from nova.console import rpcapi as console_rpcapi
from nova import context
from nova.openstack.common import rpc
from nova import test

CONF = cfg.CONF


class ConsoleRpcAPITestCase(test.NoDBTestCase):
    def _test_console_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = console_rpcapi.ConsoleAPI()
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
        expected_args = [ctxt, CONF.console_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_add_console(self):
        self._test_console_api('add_console', instance_id='i',
                               rpc_method='cast')

    def test_remove_console(self):
        self._test_console_api('remove_console', console_id='i',
                               rpc_method='cast')
