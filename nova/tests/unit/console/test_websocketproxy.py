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

"""Tests for nova websocketproxy."""


import mock

import socket

from nova.console import websocketproxy
from nova import exception
from nova import test


class NovaProxyRequestHandlerBaseTestCase(test.NoDBTestCase):

    def setUp(self):
        super(NovaProxyRequestHandlerBaseTestCase, self).setUp()

        self.flags(allowed_origins=['allowed-origin-example-1.net',
                                    'allowed-origin-example-2.net'],
                   group='console')
        self.wh = websocketproxy.NovaProxyRequestHandlerBase()
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()

    fake_header = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_ipv6 = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://[2001:db8::1]:6080',
        'Host': '[2001:db8::1]:6080',
    }

    fake_header_bad_token = {
        'cookie': 'token="XXX"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_bad_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://bad-origin-example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_allowed_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://allowed-origin-example-2.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_blank_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': '',
        'Host': 'example.net:6080',
    }

    fake_header_no_origin = {
        'cookie': 'token="123-456-789"',
        'Host': 'example.net:6080',
    }

    fake_header_http = {
        'cookie': 'token="123-456-789"',
        'Origin': 'http://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_malformed_cookie = {
        'cookie': '?=!; token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_ipv6_url(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'https://[2001:db8::1]:6080'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://[2001:db8::1]/?token=123-456-789"
        self.wh.headers = self.fake_header_ipv6

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_token_invalid(self, check_token):
        check_token.return_value = False

        self.wh.path = "http://127.0.0.1/?token=XXX"
        self.wh.headers = self.fake_header_bad_token

        self.assertRaises(exception.InvalidToken,
                          self.wh.new_websocket_client)
        check_token.assert_called_with(mock.ANY, token="XXX")

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_internal_access_path(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'vmid',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }

        tsock = mock.MagicMock()
        tsock.recv.return_value = "HTTP/1.1 200 OK\r\n\r\n"

        self.wh.socket.return_value = tsock
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_internal_access_path_err(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'xxx',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }

        tsock = mock.MagicMock()
        tsock.recv.return_value = "HTTP/1.1 500 Internal Server Error\r\n\r\n"

        self.wh.socket.return_value = tsock
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.InvalidConnectionInfo,
                          self.wh.new_websocket_client)
        check_token.assert_called_with(mock.ANY, token="123-456-789")

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_internal_access_path_rfb(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'vmid',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }

        tsock = mock.MagicMock()
        HTTP_RESP = "HTTP/1.1 200 OK\r\n\r\n"
        RFB_MSG = "RFB 003.003\n"
        # RFB negotiation message may arrive earlier.
        tsock.recv.side_effect = [HTTP_RESP + RFB_MSG,
                                  HTTP_RESP]

        self.wh.socket.return_value = tsock
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        tsock.recv.assert_has_calls([mock.call(4096, socket.MSG_PEEK),
                                     mock.call(len(HTTP_RESP))])
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch.object(websocketproxy, 'sys')
    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_py273_good_scheme(
            self, check_token, mock_sys):
        mock_sys.version_info.return_value = (2, 7, 3)
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch.object(websocketproxy, 'sys')
    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_py273_special_scheme(
            self, check_token, mock_sys):
        mock_sys.version_info = (2, 7, 3)
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "ws://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.NovaException,
                          self.wh.new_websocket_client)

    @mock.patch('socket.getfqdn')
    def test_address_string_doesnt_do_reverse_dns_lookup(self, getfqdn):
        request_mock = mock.MagicMock()
        request_mock.makefile().readline.side_effect = [
            b'GET /vnc.html?token=123-456-789 HTTP/1.1\r\n',
            b''
        ]
        server_mock = mock.MagicMock()
        client_address = ('8.8.8.8', 54321)

        handler = websocketproxy.NovaProxyRequestHandler(
            request_mock, client_address, server_mock)
        handler.log_message('log message using client address context info')

        self.assertFalse(getfqdn.called)  # no reverse dns look up
        self.assertEqual(handler.address_string(), '8.8.8.8')  # plain address

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_bad_origin_header(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_bad_origin

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_allowed_origin_header(self,
                                                              check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_allowed_origin

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_blank_origin_header(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_blank_origin

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_no_origin_header(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_no_origin

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_https_origin_proto_http(self,
                                                                check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'http://example.net:6080'
        }

        self.wh.path = "https://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_https_origin_proto_ws(self,
                                                              check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'serial',
            'access_url': 'ws://example.net:6080'
        }

        self.wh.path = "https://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_novnc_bad_console_type(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'bad-console-type'
        }

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_malformed_cookie(self, check_token):
        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url': 'https://example.net:6080'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_malformed_cookie

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')
