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

from nova.console import websocketproxy
from nova import exception
from nova import test
from oslo.config import cfg

CONF = cfg.CONF


class NovaProxyRequestHandlerBaseTestCase(test.TestCase):

    def setUp(self):
        super(NovaProxyRequestHandlerBaseTestCase, self).setUp()

        self.wh = websocketproxy.NovaWebSocketProxy()
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()
        CONF.set_override('novncproxy_base_url',
                          'https://example.net:6080/vnc_auto.html')
        CONF.set_override('html5proxy_base_url',
                          'https://example.net:6080/vnc_auto.html',
                          'spice')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_client(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'https://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.wh.new_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_client_raises_with_invalid_origin(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'https://bad-origin-example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.assertRaises(exception.ValidationError,
                          self.wh.new_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_client_raises_with_blank_origin(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return ''
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.assertRaises(exception.ValidationError,
                          self.wh.new_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_client_with_no_origin(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return None
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.wh.new_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_client_raises_with_wrong_proto_vnc(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'http://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.assertRaises(exception.ValidationError,
                          self.wh.new_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_raises_with_wrong_proto_spice(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'http://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'spice-html5'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.assertRaises(exception.ValidationError,
                          self.wh.new_client)

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_raises_with_bad_console_type(self, check_token):
        def _fake_getheader(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'https://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        check_token.return_value = {
            'host': 'node1',
            'port': '10000',
            'console_type': 'bad-console-type'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers.getheader = _fake_getheader

        self.assertRaises(exception.ValidationError,
                          self.wh.new_client)
