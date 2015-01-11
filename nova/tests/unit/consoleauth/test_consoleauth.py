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

from mox3 import mox
from oslo_utils import timeutils

from nova.consoleauth import manager
from nova import context
from nova import db
from nova import test


class ConsoleauthTestCase(test.TestCase):
    """Test Case for consoleauth."""

    def setUp(self):
        super(ConsoleauthTestCase, self).setUp()
        self.manager_api = self.manager = manager.ConsoleAuthManager()
        self.context = context.get_admin_context()
        self.instance = db.instance_create(self.context, {})

    def test_tokens_expire(self):
        # Test that tokens expire correctly.
        self.useFixture(test.TimeOverride())
        token = u'mytok'
        self.flags(console_token_ttl=1)

        self._stub_validate_console_port(True)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                         '127.0.0.1', '8080', 'host',
                                         self.instance['uuid'])
        self.assertTrue(self.manager_api.check_token(self.context, token))
        timeutils.advance_time_seconds(1)
        self.assertFalse(self.manager_api.check_token(self.context, token))

    def _stub_validate_console_port(self, result):
        def fake_validate_console_port(ctxt, instance, port, console_type):
            return result

        self.stubs.Set(self.manager.compute_rpcapi,
                       'validate_console_port',
                       fake_validate_console_port)

    def test_multiple_tokens_for_instance(self):
        tokens = [u"token" + str(i) for i in xrange(10)]

        self._stub_validate_console_port(True)

        for token in tokens:
            self.manager_api.authorize_console(self.context, token, 'novnc',
                                          '127.0.0.1', '8080', 'host',
                                          self.instance['uuid'])

        for token in tokens:
            self.assertTrue(self.manager_api.check_token(self.context, token))

    def test_delete_tokens_for_instance(self):
        tokens = [u"token" + str(i) for i in xrange(10)]
        for token in tokens:
            self.manager_api.authorize_console(self.context, token, 'novnc',
                                          '127.0.0.1', '8080', 'host',
                                          self.instance['uuid'])
        self.manager_api.delete_tokens_for_instance(self.context,
                self.instance['uuid'])
        stored_tokens = self.manager._get_tokens_for_instance(
                self.instance['uuid'])

        self.assertEqual(len(stored_tokens), 0)

        for token in tokens:
            self.assertFalse(self.manager_api.check_token(self.context, token))

    def test_wrong_token_has_port(self):
        token = u'mytok'

        self._stub_validate_console_port(False)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                        '127.0.0.1', '8080', 'host',
                                        instance_uuid=self.instance['uuid'])
        self.assertFalse(self.manager_api.check_token(self.context, token))

    def test_delete_expired_tokens(self):
        self.useFixture(test.TimeOverride())
        token = u'mytok'
        self.flags(console_token_ttl=1)

        self._stub_validate_console_port(True)

        self.manager_api.authorize_console(self.context, token, 'novnc',
                                         '127.0.0.1', '8080', 'host',
                                         self.instance['uuid'])
        timeutils.advance_time_seconds(1)
        self.assertFalse(self.manager_api.check_token(self.context, token))

        token1 = u'mytok2'
        self.manager_api.authorize_console(self.context, token1, 'novnc',
                                       '127.0.0.1', '8080', 'host',
                                       self.instance['uuid'])
        stored_tokens = self.manager._get_tokens_for_instance(
                self.instance['uuid'])
        # when trying to store token1, expired token is removed fist.
        self.assertEqual(len(stored_tokens), 1)
        self.assertEqual(stored_tokens[0], token1)


class ControlauthMemcacheEncodingTestCase(test.TestCase):
    def setUp(self):
        super(ControlauthMemcacheEncodingTestCase, self).setUp()
        self.manager = manager.ConsoleAuthManager()
        self.context = context.get_admin_context()
        self.u_token = u"token"
        self.u_instance = u"instance"

    def test_authorize_console_encoding(self):
        self.mox.StubOutWithMock(self.manager.mc, "set")
        self.mox.StubOutWithMock(self.manager.mc, "get")
        self.manager.mc.set(mox.IsA(str), mox.IgnoreArg(), mox.IgnoreArg()
                           ).AndReturn(True)
        self.manager.mc.get(mox.IsA(str)).AndReturn(None)
        self.manager.mc.set(mox.IsA(str), mox.IgnoreArg()).AndReturn(True)

        self.mox.ReplayAll()

        self.manager.authorize_console(self.context, self.u_token, 'novnc',
                                       '127.0.0.1', '8080', 'host',
                                       self.u_instance)

    def test_check_token_encoding(self):
        self.mox.StubOutWithMock(self.manager.mc, "get")
        self.manager.mc.get(mox.IsA(str)).AndReturn(None)

        self.mox.ReplayAll()

        self.manager.check_token(self.context, self.u_token)

    def test_delete_tokens_for_instance_encoding(self):
        self.mox.StubOutWithMock(self.manager.mc, "delete")
        self.mox.StubOutWithMock(self.manager.mc, "get")
        self.manager.mc.get(mox.IsA(str)).AndReturn('["token"]')
        self.manager.mc.delete(mox.IsA(str)).AndReturn(True)
        self.manager.mc.delete(mox.IsA(str)).AndReturn(True)

        self.mox.ReplayAll()

        self.manager.delete_tokens_for_instance(self.context, self.u_instance)


class CellsConsoleauthTestCase(ConsoleauthTestCase):
    """Test Case for consoleauth w/ cells enabled."""

    def setUp(self):
        super(CellsConsoleauthTestCase, self).setUp()
        self.flags(enable=True, group='cells')

    def _stub_validate_console_port(self, result):
        def fake_validate_console_port(ctxt, instance_uuid, console_port,
                                       console_type):
            return result

        self.stubs.Set(self.manager.cells_rpcapi,
                       'validate_console_port',
                       fake_validate_console_port)
