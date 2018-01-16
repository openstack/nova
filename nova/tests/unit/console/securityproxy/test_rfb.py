# Copyright (c) 2014-2016 Red Hat, Inc
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

"""Tests the Console Security Proxy Framework."""

import six

import mock

from nova.console.rfb import auth
from nova.console.rfb import authnone
from nova.console.securityproxy import rfb
from nova import exception
from nova import test


class RFBSecurityProxyTestCase(test.NoDBTestCase):
    """Test case for the base RFBSecurityProxy."""

    def setUp(self):
        super(RFBSecurityProxyTestCase, self).setUp()
        self.manager = mock.Mock()
        self.tenant_sock = mock.Mock()
        self.compute_sock = mock.Mock()

        self.tenant_sock.recv.side_effect = []
        self.compute_sock.recv.side_effect = []

        self.expected_manager_calls = []
        self.expected_tenant_calls = []
        self.expected_compute_calls = []

        self.proxy = rfb.RFBSecurityProxy()

    def _assert_expected_calls(self):
        self.assertEqual(self.expected_manager_calls,
                         self.manager.mock_calls)
        self.assertEqual(self.expected_tenant_calls,
                         self.tenant_sock.mock_calls)
        self.assertEqual(self.expected_compute_calls,
                         self.compute_sock.mock_calls)

    def _version_handshake(self):
        full_version_str = "RFB 003.008\n"

        self._expect_compute_recv(auth.VERSION_LENGTH, full_version_str)
        self._expect_compute_send(full_version_str)

        self._expect_tenant_send(full_version_str)
        self._expect_tenant_recv(auth.VERSION_LENGTH, full_version_str)

    def _to_binary(self, val):
        if not isinstance(val, six.binary_type):
            val = six.binary_type(val, 'utf-8')
        return val

    def _expect_tenant_send(self, val):
        val = self._to_binary(val)
        self.expected_tenant_calls.append(mock.call.sendall(val))

    def _expect_compute_send(self, val):
        val = self._to_binary(val)
        self.expected_compute_calls.append(mock.call.sendall(val))

    def _expect_tenant_recv(self, amt, ret_val):
        ret_val = self._to_binary(ret_val)
        self.expected_tenant_calls.append(mock.call.recv(amt))
        self.tenant_sock.recv.side_effect = (
            list(self.tenant_sock.recv.side_effect) + [ret_val])

    def _expect_compute_recv(self, amt, ret_val):
        ret_val = self._to_binary(ret_val)
        self.expected_compute_calls.append(mock.call.recv(amt))
        self.compute_sock.recv.side_effect = (
            list(self.compute_sock.recv.side_effect) + [ret_val])

    def test_fail(self):
        """Validate behavior for invalid initial message from tenant.

        The spec defines the sequence that should be used in the handshaking
        process. Anything outside of this is invalid.
        """
        self._expect_tenant_send("\x00\x00\x00\x01\x00\x00\x00\x04blah")

        self.proxy._fail(self.tenant_sock, None, 'blah')

        self._assert_expected_calls()

    def test_fail_server_message(self):
        """Validate behavior for invalid initial message from server.

        The spec defines the sequence that should be used in the handshaking
        process. Anything outside of this is invalid.
        """
        self._expect_tenant_send("\x00\x00\x00\x01\x00\x00\x00\x04blah")
        self._expect_compute_send("\x00")

        self.proxy._fail(self.tenant_sock, self.compute_sock, 'blah')

        self._assert_expected_calls()

    def test_parse_version(self):
        """Validate behavior of version parser."""
        res = self.proxy._parse_version("RFB 012.034\n")
        self.assertEqual(12.34, res)

    def test_fails_on_compute_version(self):
        """Validate behavior for unsupported compute RFB version.

        We only support RFB protocol version 3.8.
        """
        for full_version_str in ["RFB 003.007\n", "RFB 003.009\n"]:
            self._expect_compute_recv(auth.VERSION_LENGTH, full_version_str)

            ex = self.assertRaises(exception.SecurityProxyNegotiationFailed,
                                   self.proxy.connect,
                                   self.tenant_sock,
                                   self.compute_sock)
            self.assertIn('version 3.8, but server', six.text_type(ex))
            self._assert_expected_calls()

    def test_fails_on_tenant_version(self):
        """Validate behavior for unsupported tenant RFB version.

        We only support RFB protocol version 3.8.
        """
        full_version_str = "RFB 003.008\n"

        for full_version_str_invalid in ["RFB 003.007\n", "RFB 003.009\n"]:
            self._expect_compute_recv(auth.VERSION_LENGTH, full_version_str)
            self._expect_compute_send(full_version_str)

            self._expect_tenant_send(full_version_str)
            self._expect_tenant_recv(auth.VERSION_LENGTH,
                                     full_version_str_invalid)

            ex = self.assertRaises(exception.SecurityProxyNegotiationFailed,
                                   self.proxy.connect,
                                   self.tenant_sock,
                                   self.compute_sock)
            self.assertIn('version 3.8, but tenant', six.text_type(ex))
            self._assert_expected_calls()

    def test_fails_on_sec_type_cnt_zero(self):
        """Validate behavior if a server returns 0 supported security types.

        This indicates a random issue and the cause of that issues should be
        decoded and reported in the exception.
        """
        self.proxy._fail = mock.Mock()

        self._version_handshake()

        self._expect_compute_recv(1, "\x00")
        self._expect_compute_recv(4, "\x00\x00\x00\x06")
        self._expect_compute_recv(6, "cheese")
        self._expect_tenant_send("\x00\x00\x00\x00\x06cheese")

        ex = self.assertRaises(exception.SecurityProxyNegotiationFailed,
                               self.proxy.connect,
                               self.tenant_sock,
                               self.compute_sock)
        self.assertIn('cheese', six.text_type(ex))

        self._assert_expected_calls()

    @mock.patch.object(authnone.RFBAuthSchemeNone, "security_handshake")
    def test_full_run(self, mock_handshake):
        """Validate correct behavior."""
        new_sock = mock.MagicMock()
        mock_handshake.return_value = new_sock

        self._version_handshake()

        self._expect_compute_recv(1, "\x02")
        self._expect_compute_recv(2, "\x01\x02")

        self._expect_tenant_send("\x01\x01")
        self._expect_tenant_recv(1, "\x01")

        self._expect_compute_send("\x01")

        self.assertEqual(new_sock, self.proxy.connect(
            self.tenant_sock, self.compute_sock))

        mock_handshake.assert_called_once_with(self.compute_sock)
        self._assert_expected_calls()

    def test_client_auth_invalid_fails(self):
        """Validate behavior if no security types are supported."""
        self.proxy._fail = self.manager.proxy._fail
        self.proxy.security_handshake = self.manager.proxy.security_handshake

        self._version_handshake()

        self._expect_compute_recv(1, "\x02")
        self._expect_compute_recv(2, "\x01\x02")

        self._expect_tenant_send("\x01\x01")
        self._expect_tenant_recv(1, "\x02")

        self.expected_manager_calls.append(
            mock.call.proxy._fail(self.tenant_sock,
                                  self.compute_sock,
                                  "Only the security type "
                                  "None (1) is supported"))

        self.assertRaises(exception.SecurityProxyNegotiationFailed,
                          self.proxy.connect,
                          self.tenant_sock,
                          self.compute_sock)
        self._assert_expected_calls()

    def test_exception_in_choose_security_type_fails(self):
        """Validate behavior if a given security type isn't supported."""
        self.proxy._fail = self.manager.proxy._fail
        self.proxy.security_handshake = self.manager.proxy.security_handshake

        self._version_handshake()

        self._expect_compute_recv(1, "\x02")
        self._expect_compute_recv(2, "\x02\x05")

        self._expect_tenant_send("\x01\x01")
        self._expect_tenant_recv(1, "\x01")

        self.expected_manager_calls.extend([
            mock.call.proxy._fail(
                self.tenant_sock, self.compute_sock,
                'Unable to negotiate security with server')])

        self.assertRaises(exception.SecurityProxyNegotiationFailed,
                          self.proxy.connect,
                          self.tenant_sock,
                          self.compute_sock)

        self._assert_expected_calls()

    @mock.patch.object(authnone.RFBAuthSchemeNone, "security_handshake")
    def test_exception_security_handshake_fails(self, mock_auth):
        """Validate behavior if the security handshake fails for any reason."""
        self.proxy._fail = self.manager.proxy._fail

        self._version_handshake()

        self._expect_compute_recv(1, "\x02")
        self._expect_compute_recv(2, "\x01\x02")

        self._expect_tenant_send("\x01\x01")
        self._expect_tenant_recv(1, "\x01")

        self._expect_compute_send("\x01")

        ex = exception.RFBAuthHandshakeFailed(reason="crackers")
        mock_auth.side_effect = ex

        self.expected_manager_calls.extend([
            mock.call.proxy._fail(self.tenant_sock, None,
                                  'Unable to negotiate security with server')])

        self.assertRaises(exception.SecurityProxyNegotiationFailed,
                          self.proxy.connect,
                          self.tenant_sock,
                          self.compute_sock)

        mock_auth.assert_called_once_with(self.compute_sock)
        self._assert_expected_calls()
