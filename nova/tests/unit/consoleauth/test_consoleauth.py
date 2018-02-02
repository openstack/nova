# Copyright 2012 OpenStack Foundation
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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
Tests for Consoleauth Code.

"""

import mock
from oslo_utils import timeutils
import six

from nova.consoleauth import manager
from nova import context
from nova import objects
from nova import test
from nova.tests import uuidsentinel as uuids


class ConsoleauthTestCase(test.NoDBTestCase):
    """Test Case for consoleauth."""

    rpcapi = 'nova.compute.rpcapi.ComputeAPI.'

    def setUp(self):
        super(ConsoleauthTestCase, self).setUp()
        self.manager_api = self.manager = manager.ConsoleAuthManager()
        self.context = context.get_admin_context()
        self.instance_uuid = '00000000-0000-0000-0000-000000000000'
        self.is_cells = False

    def test_reset(self):
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            old_rpcapi = self.manager_api.compute_rpcapi
            self.manager_api.reset()
            mock_rpc.assert_called_once_with()
            self.assertNotEqual(old_rpcapi,
                                self.manager_api.compute_rpcapi)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_tokens_expire(self, mock_get):
        mock_get.return_value = None
        # NOTE(danms): Get the faked InstanceMapping from the SingleCellSimple
        # fixture so we can return it from our own mock to verify
        # that it was called
        fake_im = objects.InstanceMapping.get_by_instance_uuid(self.context,
                uuids.instance)

        # Test that tokens expire correctly.
        self.useFixture(test.TimeOverride())
        token = u'mytok'
        self.flags(token_ttl=1, group='consoleauth')

        self._stub_validate_console_port(True)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                         '127.0.0.1', '8080', 'host',
                                         self.instance_uuid)
        with mock.patch('nova.objects.InstanceMapping.'
                        'get_by_instance_uuid') as mock_get:
            mock_get.return_value = fake_im
            self.assertIsNotNone(self.manager_api.check_token(self.context,
                                                              token))
            timeutils.advance_time_seconds(1)
            self.assertIsNone(self.manager_api.check_token(self.context,
                                                           token))
            if not self.is_cells:
                mock_get.assert_called_once_with(self.context,
                                                 self.instance_uuid)

    def _stub_validate_console_port(self, result):
        def fake_validate_console_port(self, ctxt, instance,
                                       port, console_type):
            return result

        self.stub_out(self.rpcapi + 'validate_console_port',
                      fake_validate_console_port)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_multiple_tokens_for_instance(self, mock_get):
        mock_get.return_value = None

        tokens = [u"token" + str(i) for i in range(10)]

        self._stub_validate_console_port(True)

        for token in tokens:
            self.manager_api.authorize_console(self.context, token, 'novnc',
                                          '127.0.0.1', '8080', 'host',
                                          self.instance_uuid)

        for token in tokens:
            self.assertIsNotNone(
                    self.manager_api.check_token(self.context, token))

    def test_delete_tokens_for_instance(self):
        tokens = [u"token" + str(i) for i in range(10)]
        for token in tokens:
            self.manager_api.authorize_console(self.context, token, 'novnc',
                                          '127.0.0.1', '8080', 'host',
                                          self.instance_uuid)
        self.manager_api.delete_tokens_for_instance(self.context,
                self.instance_uuid)
        stored_tokens = self.manager._get_tokens_for_instance(
                self.instance_uuid)

        self.assertEqual(len(stored_tokens), 0)

        for token in tokens:
            self.assertIsNone(
                self.manager_api.check_token(self.context, token))

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_wrong_token_has_port(self, mock_get):
        mock_get.return_value = None

        token = u'mytok'

        self._stub_validate_console_port(False)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                        '127.0.0.1', '8080', 'host',
                                        instance_uuid=self.instance_uuid)
        self.assertIsNone(self.manager_api.check_token(self.context, token))

    def test_delete_expired_tokens(self):
        self.useFixture(test.TimeOverride())
        token = u'mytok'
        self.flags(token_ttl=1, group='consoleauth')

        self._stub_validate_console_port(True)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                         '127.0.0.1', '8080', 'host',
                                         self.instance_uuid)
        timeutils.advance_time_seconds(1)
        self.assertIsNone(self.manager_api.check_token(self.context, token))

        token1 = u'mytok2'
        self.manager_api.authorize_console(self.context, token1, 'novnc',
                                       '127.0.0.1', '8080', 'host',
                                       self.instance_uuid)
        stored_tokens = self.manager._get_tokens_for_instance(
                self.instance_uuid)
        # when trying to store token1, expired token is removed fist.
        self.assertEqual(len(stored_tokens), 1)
        self.assertEqual(stored_tokens[0], token1)


class ControlauthMemcacheEncodingTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ControlauthMemcacheEncodingTestCase, self).setUp()
        self.manager = manager.ConsoleAuthManager()
        self.context = context.get_admin_context()
        self.u_token = u"token"
        self.u_instance = u"instance"

    def test_authorize_console_encoding(self):
        with test.nested(
                mock.patch.object(self.manager.mc_instance,
                                  'set', return_value=None),
                mock.patch.object(self.manager.mc_instance,
                                  'get', return_value='["token"]'),
                mock.patch.object(self.manager.mc,
                                  'set', return_value=None),
                mock.patch.object(self.manager.mc,
                                  'get', return_value=None),
                mock.patch.object(self.manager.mc,
                                  'get_multi', return_value=["token1"]),
        ) as (
                mock_instance_set,
                mock_instance_get,
                mock_set,
                mock_get,
                mock_get_multi):
            self.manager.authorize_console(self.context, self.u_token,
                                           'novnc', '127.0.0.1', '8080',
                                           'host', self.u_instance)
            mock_set.assert_has_calls([mock.call(b'token', mock.ANY)])
            mock_instance_get.assert_has_calls([mock.call(b'instance')])
            mock_get_multi.assert_has_calls([mock.call([b'token'])])
            mock_instance_set.assert_has_calls(
                    [mock.call(b'instance', mock.ANY)])

    def test_check_token_encoding(self):
        with mock.patch.object(self.manager.mc,
                               "get",
                               return_value=None) as mock_get:
            self.manager.check_token(self.context, self.u_token)
            mock_get.assert_called_once_with(test.MatchType(six.binary_type))

    def test_delete_tokens_for_instance_encoding(self):
        with test.nested(
                mock.patch.object(self.manager.mc_instance,
                                  'get', return_value='["token"]'),
                mock.patch.object(self.manager.mc_instance,
                                  'delete', return_value=True),
                mock.patch.object(self.manager.mc,
                                  'get'),
                mock.patch.object(self.manager.mc,
                                  'delete_multi', return_value=True),
        ) as (
                mock_instance_get,
                mock_instance_delete,
                mock_get,
                mock_delete_multi):
            self.manager.delete_tokens_for_instance(self.context,
                                                    self.u_instance)
            mock_instance_get.assert_has_calls([mock.call(b'instance')])
            mock_instance_delete.assert_has_calls([mock.call(b'instance')])
            mock_delete_multi.assert_has_calls([mock.call([b'token'])])


class CellsConsoleauthTestCase(ConsoleauthTestCase):
    """Test Case for consoleauth w/ cells enabled."""

    rpcapi = 'nova.cells.rpcapi.CellsAPI.'

    def setUp(self):
        super(CellsConsoleauthTestCase, self).setUp()
        self.flags(enable=True, group='cells')
        self.is_cells = True
