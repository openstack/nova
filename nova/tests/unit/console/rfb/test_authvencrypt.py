# Copyright (c) 2016 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import ssl
import struct

import mock

from nova.console.rfb import auth
from nova.console.rfb import authvencrypt
from nova import exception
from nova import test


class RFBAuthSchemeVeNCryptTestCase(test.NoDBTestCase):

    def setUp(self):
        super(RFBAuthSchemeVeNCryptTestCase, self).setUp()

        self.scheme = authvencrypt.RFBAuthSchemeVeNCrypt()
        self.compute_sock = mock.MagicMock()

        self.compute_sock.recv.side_effect = []

        self.expected_calls = []

        self.flags(vencrypt_ca_certs="/certs/ca.pem", group="vnc")

    def _expect_send(self, val):
        self.expected_calls.append(mock.call.sendall(val))

    def _expect_recv(self, amt, ret_val):
        self.expected_calls.append(mock.call.recv(amt))
        self.compute_sock.recv.side_effect = (
            list(self.compute_sock.recv.side_effect) + [ret_val])

    @mock.patch.object(ssl, "wrap_socket", return_value="wrapped")
    def test_security_handshake_with_x509(self, mock_socket):
        self.flags(vencrypt_client_key='/certs/keyfile',
                   vencrypt_client_cert='/certs/cert.pem',
                   group="vnc")

        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x00")

        self._expect_recv(1, "\x02")
        subtypes_raw = [authvencrypt.AuthVeNCryptSubtype.X509NONE,
                        authvencrypt.AuthVeNCryptSubtype.X509VNC]
        subtypes = struct.pack('!2I', *subtypes_raw)
        self._expect_recv(8, subtypes)

        self._expect_send(struct.pack('!I', subtypes_raw[0]))

        self._expect_recv(1, "\x01")

        self.assertEqual("wrapped", self.scheme.security_handshake(
            self.compute_sock))

        mock_socket.assert_called_once_with(
            self.compute_sock,
            keyfile='/certs/keyfile',
            certfile='/certs/cert.pem',
            server_side=False,
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs='/certs/ca.pem')

        self.assertEqual(self.expected_calls, self.compute_sock.mock_calls)

    @mock.patch.object(ssl, "wrap_socket", return_value="wrapped")
    def test_security_handshake_without_x509(self, mock_socket):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x00")

        self._expect_recv(1, "\x02")
        subtypes_raw = [authvencrypt.AuthVeNCryptSubtype.X509NONE,
                        authvencrypt.AuthVeNCryptSubtype.X509VNC]
        subtypes = struct.pack('!2I', *subtypes_raw)
        self._expect_recv(8, subtypes)

        self._expect_send(struct.pack('!I', subtypes_raw[0]))

        self._expect_recv(1, "\x01")

        self.assertEqual("wrapped", self.scheme.security_handshake(
            self.compute_sock))
        mock_socket.assert_called_once_with(
            self.compute_sock,
            keyfile=None,
            certfile=None,
            server_side=False,
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs='/certs/ca.pem'
        )

        self.assertEqual(self.expected_calls, self.compute_sock.mock_calls)

    def _test_security_handshake_fails(self):
        self.assertRaises(exception.RFBAuthHandshakeFailed,
                          self.scheme.security_handshake,
                          self.compute_sock)
        self.assertEqual(self.expected_calls, self.compute_sock.mock_calls)

    def test_security_handshake_fails_on_low_version(self):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x01")

        self._test_security_handshake_fails()

    def test_security_handshake_fails_on_cant_use_version(self):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x01")

        self._test_security_handshake_fails()

    def test_security_handshake_fails_on_missing_subauth(self):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x00")

        self._expect_recv(1, "\x01")
        subtypes_raw = [authvencrypt.AuthVeNCryptSubtype.X509VNC]
        subtypes = struct.pack('!I', *subtypes_raw)
        self._expect_recv(4, subtypes)

        self._test_security_handshake_fails()

    def test_security_handshake_fails_on_auth_not_accepted(self):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x00")

        self._expect_recv(1, "\x02")
        subtypes_raw = [authvencrypt.AuthVeNCryptSubtype.X509NONE,
                        authvencrypt.AuthVeNCryptSubtype.X509VNC]
        subtypes = struct.pack('!2I', *subtypes_raw)
        self._expect_recv(8, subtypes)

        self._expect_send(struct.pack('!I', subtypes_raw[0]))

        self._expect_recv(1, "\x00")

        self._test_security_handshake_fails()

    @mock.patch.object(ssl, "wrap_socket")
    def test_security_handshake_fails_on_ssl_failure(self, mock_socket):
        self._expect_recv(1, "\x00")
        self._expect_recv(1, "\x02")

        self._expect_send(b"\x00\x02")
        self._expect_recv(1, "\x00")

        self._expect_recv(1, "\x02")
        subtypes_raw = [authvencrypt.AuthVeNCryptSubtype.X509NONE,
                        authvencrypt.AuthVeNCryptSubtype.X509VNC]
        subtypes = struct.pack('!2I', *subtypes_raw)
        self._expect_recv(8, subtypes)

        self._expect_send(struct.pack('!I', subtypes_raw[0]))

        self._expect_recv(1, "\x01")

        mock_socket.side_effect = ssl.SSLError("cheese")

        self._test_security_handshake_fails()

        mock_socket.assert_called_once_with(
            self.compute_sock,
            keyfile=None,
            certfile=None,
            server_side=False,
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs='/certs/ca.pem'
        )

    def test_types(self):
        scheme = authvencrypt.RFBAuthSchemeVeNCrypt()

        self.assertEqual(auth.AuthType.VENCRYPT,
                         scheme.security_type())
