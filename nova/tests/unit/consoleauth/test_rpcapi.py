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
Unit Tests for nova.consoleauth.rpcapi
"""

import contextlib

import mock
from oslo.config import cfg

from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context
from nova import test

CONF = cfg.CONF


class ConsoleAuthRpcAPITestCase(test.NoDBTestCase):
    def _test_consoleauth_api(self, method, **kwargs):
        do_cast = kwargs.pop('_do_cast', False)

        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic, CONF.consoleauth_topic)

        orig_prepare = rpcapi.client.prepare

        with contextlib.nested(
            mock.patch.object(rpcapi.client, 'cast' if do_cast else 'call'),
            mock.patch.object(rpcapi.client, 'prepare'),
            mock.patch.object(rpcapi.client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):
            prepare_mock.return_value = rpcapi.client
            rpc_mock.return_value = None if do_cast else 'foo'
            csv_mock.side_effect = (
                lambda v: orig_prepare().can_send_version())

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, rpc_mock.return_value)

            prepare_mock.assert_called_once_with()
            rpc_mock.assert_called_once_with(ctxt, method, **kwargs)

    def test_authorize_console(self):
        self._test_consoleauth_api('authorize_console', token='token',
                console_type='ctype', host='h', port='p',
                internal_access_path='iap', instance_uuid="instance")

    def test_check_token(self):
        self._test_consoleauth_api('check_token', token='t')

    def test_delete_tokens_for_instnace(self):
        self._test_consoleauth_api('delete_tokens_for_instance',
                                   _do_cast=True,
                                   instance_uuid="instance")
