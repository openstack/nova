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

import mock

from nova.console import rpcapi as console_rpcapi
from nova import context
from nova import test


class ConsoleRpcAPITestCase(test.NoDBTestCase):
    def _test_console_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = console_rpcapi.ConsoleAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic,
                         console_rpcapi.RPC_TOPIC)

        orig_prepare = rpcapi.client.prepare

        with test.nested(
            mock.patch.object(rpcapi.client, rpc_method),
            mock.patch.object(rpcapi.client, 'prepare'),
            mock.patch.object(rpcapi.client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):
            prepare_mock.return_value = rpcapi.client
            rpc_mock.return_value = 'foo' if rpc_method == 'call' else None
            csv_mock.side_effect = (
                lambda v: orig_prepare().can_send_version())

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, rpc_mock.return_value)

            prepare_mock.assert_called_once_with()
            rpc_mock.assert_called_once_with(ctxt, method, **kwargs)

    def test_add_console(self):
        self._test_console_api('add_console', instance_id='i',
                               rpc_method='cast')

    def test_remove_console(self):
        self._test_console_api('remove_console', console_id='i',
                               rpc_method='cast')
