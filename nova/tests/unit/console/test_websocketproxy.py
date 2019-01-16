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

import copy
import socket

import mock

import nova.conf
from nova.console.securityproxy import base
from nova.console import websocketproxy
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_console_auth_token as fake_ca
from nova.tests import uuidsentinel as uuids
from nova import utils

CONF = nova.conf.CONF


class NovaProxyRequestHandlerDBTestCase(test.TestCase):

    def setUp(self):
        super(NovaProxyRequestHandlerDBTestCase, self).setUp()

        self.flags(console_allowed_origins=['allowed-origin-example-1.net',
                                            'allowed-origin-example-2.net'])
        with mock.patch('websockify.ProxyRequestHandler'):
            self.wh = websocketproxy.NovaProxyRequestHandler()
        self.wh.server = websocketproxy.NovaWebSocketProxy()
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()

    def _fake_console_db(self, **updates):
        console_db = copy.deepcopy(fake_ca.fake_token_dict)
        console_db['token_hash'] = utils.get_sha256_str('123-456-789')
        if updates:
            console_db.update(updates)
        return console_db

    fake_header = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.validate_console_port')
    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token')
    def test_new_websocket_client_db(
            self, mock_ca_check, mock_validate_port, mock_inst_get,
            mock_validate, internal_access_path=None,
            instance_not_found=False):

        db_obj = self._fake_console_db(
            host='node1',
            port=10000,
            console_type='novnc',
            access_url_base='https://example.net:6080',
            internal_access_path=internal_access_path,
            instance_uuid=uuids.instance,
            # This is set by ConsoleAuthToken.validate
            token='123-456-789'
        )
        ctxt = nova_context.get_context()
        obj = nova.objects.ConsoleAuthToken._from_db_object(
            ctxt, nova.objects.ConsoleAuthToken(), db_obj)
        mock_validate.return_value = obj

        if instance_not_found:
            mock_inst_get.side_effect = exception.InstanceNotFound(
                instance_id=uuids.instance)

        if internal_access_path is None:
            self.wh.socket.return_value = '<socket>'
        else:
            tsock = mock.MagicMock()
            tsock.recv.return_value = "HTTP/1.1 200 OK\r\n\r\n"
            self.wh.socket.return_value = tsock

        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        if instance_not_found:
            self.assertRaises(exception.InvalidToken,
                              self.wh.new_websocket_client)
        else:
            with mock.patch('nova.context.get_admin_context',
                            return_value=ctxt):
                self.wh.new_websocket_client()

            mock_validate.called_once_with(ctxt, '123-456-789')
            mock_validate_port.assert_called_once_with(
                ctxt, mock_inst_get.return_value, str(db_obj['port']),
                db_obj['console_type'])
            mock_ca_check.assert_not_called()

            self.wh.socket.assert_called_with('node1', 10000, connect=True)

            if internal_access_path is None:
                self.wh.do_proxy.assert_called_with('<socket>')
            else:
                self.wh.do_proxy.assert_called_with(tsock)

    def test_new_websocket_client_db_internal_access_path(self):
        self.test_new_websocket_client_db(internal_access_path='vmid')

    def test_new_websocket_client_db_instance_not_found(self):
        self.test_new_websocket_client_db(instance_not_found=True)


class NovaProxyRequestHandlerBaseTestCase(test.NoDBTestCase):

    def setUp(self):
        super(NovaProxyRequestHandlerBaseTestCase, self).setUp()

        self.flags(allowed_origins=['allowed-origin-example-1.net',
                                    'allowed-origin-example-2.net'],
                   group='console')
        self.server = websocketproxy.NovaWebSocketProxy()
        with mock.patch('websockify.ProxyRequestHandler'):
            self.wh = websocketproxy.NovaProxyRequestHandler()
        self.wh.server = self.server
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
    def test_new_websocket_client_with_server_with_cells(self, check_token):
        # this test cells enabled, so consoleauth should be used
        CONF.set_override('enable', True, group='cells')
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
    def test_new_websocket_client_enable_consoleauth(self, check_token):
        self.flags(enable_consoleauth=True, group='workarounds')

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

    @mock.patch('nova.consoleauth.rpcapi.ConsoleAuthAPI.check_token',
                return_value=None)
    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_enable_consoleauth_fallback(self, validate,
                                                              check_port,
                                                              check_token):
        # Since consoleauth is enabled, it should be called first before
        # falling back to the database.
        self.flags(enable_consoleauth=True, group='workarounds')

        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        check_token.assert_called_with(mock.ANY, token="123-456-789")
        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client(self, validate, check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_ipv6_url(self, validate, check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://[2001:db8::1]:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://[2001:db8::1]/?token=123-456-789"
        self.wh.headers = self.fake_header_ipv6

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_token_invalid(self, validate):
        validate.side_effect = exception.InvalidToken(token='XXX')

        self.wh.path = "http://127.0.0.1/?token=XXX"
        self.wh.headers = self.fake_header_bad_token

        self.assertRaises(exception.InvalidToken,
                          self.wh.new_websocket_client)
        validate.assert_called_with(mock.ANY, "XXX")

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_internal_access_path(self, validate,
                                                       check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'vmid',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        tsock = mock.MagicMock()
        tsock.recv.return_value = "HTTP/1.1 200 OK\r\n\r\n"

        self.wh.socket.return_value = tsock
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        tsock.send.assert_called_with(test.MatchType(bytes))
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_internal_access_path_err(self, validate,
                                                           check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'xxx',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        tsock = mock.MagicMock()
        tsock.recv.return_value = "HTTP/1.1 500 Internal Server Error\r\n\r\n"

        self.wh.socket.return_value = tsock
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.InvalidConnectionInfo,
                          self.wh.new_websocket_client)
        validate.assert_called_with(mock.ANY, "123-456-789")

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_internal_access_path_rfb(self, validate,
                                                           check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'internal_access_path': 'vmid',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

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

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        tsock.recv.assert_has_calls([mock.call(4096, socket.MSG_PEEK),
                                     mock.call(len(HTTP_RESP))])
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch.object(websocketproxy, 'sys')
    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_py273_good_scheme(
            self, validate, check_port, mock_sys):
        mock_sys.version_info.return_value = (2, 7, 3)
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
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

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_bad_origin_header(self, validate,
                                                          check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_bad_origin

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_allowed_origin_header(self, validate,
                                                              check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_allowed_origin

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_blank_origin_header(self, validate,
                                                            check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_blank_origin

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_no_origin_header(self, validate,
                                                         check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_no_origin

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_https_origin_proto_http(
            self, validate, check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'http://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.path = "https://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_https_origin_proto_ws(self, validate,
                                                              check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'serial',
            'access_url_base': 'ws://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.path = "https://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_http_forwarded_proto_https(self, validate,
                                                             check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'serial',
            'access_url_base': 'wss://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        header = {
            'cookie': 'token="123-456-789"',
            'Origin': 'http://example.net:6080',
            'Host': 'example.net:6080',
            'X-Forwarded-Proto': 'https'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = "https://127.0.0.1/"
        self.wh.headers = header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_new_websocket_client_novnc_bad_console_type(self, validate,
                                                         check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'bad-console-type'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header

        self.assertRaises(exception.ValidationError,
                          self.wh.new_websocket_client)

    @mock.patch('nova.console.websocketproxy.NovaProxyRequestHandlerBase.'
                '_check_console_port')
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_malformed_cookie(self, validate, check_port):
        params = {
            'id': 1,
            'token': '123-456-789',
            'instance_uuid': uuids.instance,
            'host': 'node1',
            'port': '10000',
            'console_type': 'novnc',
            'access_url_base': 'https://example.net:6080'
        }
        validate.return_value = objects.ConsoleAuthToken(**params)

        self.wh.socket.return_value = '<socket>'
        self.wh.path = "http://127.0.0.1/"
        self.wh.headers = self.fake_header_malformed_cookie

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')


class NovaWebsocketSecurityProxyTestCase(test.NoDBTestCase):

    def setUp(self):
        super(NovaWebsocketSecurityProxyTestCase, self).setUp()

        self.flags(allowed_origins=['allowed-origin-example-1.net',
                                    'allowed-origin-example-2.net'],
                   group='console')

        self.server = websocketproxy.NovaWebSocketProxy(
            security_proxy=mock.MagicMock(
                spec=base.SecurityProxy)
        )

        with mock.patch('websockify.ProxyRequestHandler'):
            self.wh = websocketproxy.NovaProxyRequestHandler()
        self.wh.server = self.server
        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()

        def get_header(header):
            if header == 'cookie':
                return 'token="123-456-789"'
            elif header == 'Origin':
                return 'https://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        self.wh.headers.get = get_header

    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.validate_console_port')
    @mock.patch('nova.console.websocketproxy.TenantSock.close')
    @mock.patch('nova.console.websocketproxy.TenantSock.finish_up')
    def test_proxy_connect_ok(self, mock_finish, mock_close,
                              mock_port_validate, mock_get,
                              mock_token_validate):
        mock_token_validate.return_value = nova.objects.ConsoleAuthToken(
            instance_uuid=uuids.instance, host='node1', port='10000',
            console_type='novnc', access_url_base='https://example.net:6080')
        # The token and id attributes are set by the validate() method.
        mock_token_validate.return_value.token = '123-456-789'
        mock_token_validate.return_value.id = 1

        sock = mock.MagicMock(
            spec=websocketproxy.TenantSock)
        self.server.security_proxy.connect.return_value = sock

        self.wh.new_websocket_client()

        self.wh.do_proxy.assert_called_with(sock)
        mock_finish.assert_called_with()
        self.assertEqual(len(mock_close.calls), 0)

    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.validate_console_port')
    @mock.patch('nova.console.websocketproxy.TenantSock.close')
    @mock.patch('nova.console.websocketproxy.TenantSock.finish_up')
    def test_proxy_connect_err(self, mock_finish, mock_close,
                               mock_port_validate, mock_get,
                               mock_token_validate):
        mock_token_validate.return_value = nova.objects.ConsoleAuthToken(
            instance_uuid=uuids.instance, host='node1', port='10000',
            console_type='novnc', access_url_base='https://example.net:6080')
        # The token attribute is set by the validate() method.
        mock_token_validate.return_value.token = '123-456-789'
        mock_token_validate.return_value.id = 1

        ex = exception.SecurityProxyNegotiationFailed("Wibble")
        self.server.security_proxy.connect.side_effect = ex

        self.assertRaises(exception.SecurityProxyNegotiationFailed,
                          self.wh.new_websocket_client)

        self.assertEqual(len(self.wh.do_proxy.calls), 0)
        mock_close.assert_called_with()
        self.assertEqual(len(mock_finish.calls), 0)
