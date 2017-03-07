# Copyright 2011 United States Government as represented by the
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

"""Unit tests for `nova.wsgi`."""

import os.path
import socket
import tempfile

import eventlet
import eventlet.wsgi
import mock
from oslo_config import cfg
import requests
import six
import testtools
import webob

import nova.exception
from nova import test
from nova.tests.unit import utils
import nova.wsgi

SSL_CERT_DIR = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)),
                                'ssl_cert'))
CONF = cfg.CONF


class TestLoaderNothingExists(test.NoDBTestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super(TestLoaderNothingExists, self).setUp()
        self.stub_out('os.path.exists', lambda _: False)

    def test_relpath_config_not_found(self):
        self.flags(api_paste_config='api-paste.ini', group='wsgi')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            nova.wsgi.Loader,
        )

    def test_asbpath_config_not_found(self):
        self.flags(api_paste_config='/etc/nova/api-paste.ini', group='wsgi')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            nova.wsgi.Loader,
        )


class TestLoaderNormalFilesystem(test.NoDBTestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        super(TestLoaderNormalFilesystem, self).setUp()
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = nova.wsgi.Loader(self.config.name)

    def test_config_found(self):
        self.assertEqual(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            nova.exception.PasteAppNotFound,
            self.loader.load_app,
            "nonexistent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEqual("/tmp", url_parser.directory)

    def tearDown(self):
        self.config.close()
        super(TestLoaderNormalFilesystem, self).tearDown()


class TestWSGIServer(test.NoDBTestCase):
    """WSGI server tests."""

    def test_no_app(self):
        server = nova.wsgi.Server("test_app", None)
        self.assertEqual("test_app", server.name)

    def test_custom_max_header_line(self):
        self.flags(max_header_line=4096, group='wsgi')  # Default is 16384
        nova.wsgi.Server("test_custom_max_header_line", None)
        self.assertEqual(CONF.wsgi.max_header_line,
                         eventlet.wsgi.MAX_HEADER_LINE)

    def test_start_random_port(self):
        server = nova.wsgi.Server("test_random_port", None,
                                  host="127.0.0.1", port=0)
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_start_random_port_with_ipv6(self):
        server = nova.wsgi.Server("test_random_port", None,
            host="::1", port=0)
        server.start()
        self.assertEqual("::1", server.host)
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(not utils.is_linux(), 'SO_REUSEADDR behaves differently '
                                            'on OSX and BSD, see bugs '
                                            '1436895 and 1467145')
    def test_socket_options_for_simple_server(self):
        # test normal socket options has set properly
        self.flags(tcp_keepidle=500, group='wsgi')
        server = nova.wsgi.Server("test_socket_options", None,
                                  host="127.0.0.1", port=0)
        server.start()
        sock = server._socket
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_REUSEADDR))
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_KEEPALIVE))
        if hasattr(socket, 'TCP_KEEPIDLE'):
            self.assertEqual(CONF.wsgi.tcp_keepidle,
                             sock.getsockopt(socket.IPPROTO_TCP,
                                             socket.TCP_KEEPIDLE))
        server.stop()
        server.wait()

    def test_server_pool_waitall(self):
        # test pools waitall method gets called while stopping server
        server = nova.wsgi.Server("test_server", None,
            host="127.0.0.1")
        server.start()
        with mock.patch.object(server._pool,
                              'waitall') as mock_waitall:
            server.stop()
            server.wait()
            mock_waitall.assert_called_once_with()

    def test_uri_length_limit(self):
        server = nova.wsgi.Server("test_uri_length_limit", None,
            host="127.0.0.1", max_url_len=16384)
        server.start()

        uri = "http://127.0.0.1:%d/%s" % (server.port, 10000 * 'x')
        resp = requests.get(uri, proxies={"http": ""})
        eventlet.sleep(0)
        self.assertNotEqual(resp.status_code,
                            requests.codes.REQUEST_URI_TOO_LARGE)

        uri = "http://127.0.0.1:%d/%s" % (server.port, 20000 * 'x')
        resp = requests.get(uri, proxies={"http": ""})
        eventlet.sleep(0)
        self.assertEqual(resp.status_code,
                         requests.codes.REQUEST_URI_TOO_LARGE)
        server.stop()
        server.wait()

    def test_reset_pool_size_to_default(self):
        server = nova.wsgi.Server("test_resize", None,
            host="127.0.0.1", max_url_len=16384)
        server.start()

        # Stopping the server, which in turn sets pool size to 0
        server.stop()
        self.assertEqual(server._pool.size, 0)

        # Resetting pool size to default
        server.reset()
        server.start()
        self.assertEqual(server._pool.size, CONF.wsgi.default_pool_size)

    def test_client_socket_timeout(self):
        self.flags(client_socket_timeout=5, group='wsgi')

        # mocking eventlet spawn method to check it is called with
        # configured 'client_socket_timeout' value.
        with mock.patch.object(eventlet,
                               'spawn') as mock_spawn:
            server = nova.wsgi.Server("test_app", None,
                                      host="127.0.0.1", port=0)
            server.start()
            _, kwargs = mock_spawn.call_args
            self.assertEqual(CONF.wsgi.client_socket_timeout,
                             kwargs['socket_timeout'])
            server.stop()

    def test_keep_alive(self):
        self.flags(keep_alive=False, group='wsgi')

        # mocking eventlet spawn method to check it is called with
        # configured 'keep_alive' value.
        with mock.patch.object(eventlet,
                               'spawn') as mock_spawn:
            server = nova.wsgi.Server("test_app", None,
                                      host="127.0.0.1", port=0)
            server.start()
            _, kwargs = mock_spawn.call_args
            self.assertEqual(CONF.wsgi.keep_alive,
                             kwargs['keepalive'])
            server.stop()


@testtools.skipIf(six.PY3, "bug/1482633: test hangs on Python 3")
class TestWSGIServerWithSSL(test.NoDBTestCase):
    """WSGI server with SSL tests."""

    def setUp(self):
        super(TestWSGIServerWithSSL, self).setUp()
        self.flags(enabled_ssl_apis=['fake_ssl'])
        self.flags(
                ssl_cert_file=os.path.join(SSL_CERT_DIR, 'certificate.crt'),
                ssl_key_file=os.path.join(SSL_CERT_DIR, 'privatekey.key'),
                group='wsgi')

    def test_ssl_server(self):

        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = nova.wsgi.Server("fake_ssl", test_app,
                                           host="127.0.0.1", port=0,
                                           use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        response = requests.post(
            'https://127.0.0.1:%s/' % fake_ssl_server.port,
            verify=os.path.join(SSL_CERT_DIR, 'ca.crt'), data='PING')
        self.assertEqual(response.text, 'PONG')

        fake_ssl_server.stop()
        fake_ssl_server.wait()

    def test_two_servers(self):

        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = nova.wsgi.Server("fake_ssl", test_app,
            host="127.0.0.1", port=0, use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        fake_server = nova.wsgi.Server("fake", test_app,
            host="127.0.0.1", port=0)
        fake_server.start()
        self.assertNotEqual(0, fake_server.port)

        response = requests.post(
            'https://127.0.0.1:%s/' % fake_ssl_server.port,
            verify=os.path.join(SSL_CERT_DIR, 'ca.crt'), data='PING')
        self.assertEqual(response.text, 'PONG')

        response = requests.post('http://127.0.0.1:%s/' % fake_server.port,
                                 data='PING')
        self.assertEqual(response.text, 'PONG')

        fake_ssl_server.stop()
        fake_ssl_server.wait()
        fake_server.stop()
        fake_server.wait()

    @testtools.skipIf(not utils.is_linux(), 'SO_REUSEADDR behaves differently '
                                            'on OSX and BSD, see bugs '
                                            '1436895 and 1467145')
    def test_socket_options_for_ssl_server(self):
        # test normal socket options has set properly
        self.flags(tcp_keepidle=500, group='wsgi')
        server = nova.wsgi.Server("test_socket_options", None,
                                  host="127.0.0.1", port=0,
                                  use_ssl=True)
        server.start()
        sock = server._socket
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_REUSEADDR))
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_KEEPALIVE))
        if hasattr(socket, 'TCP_KEEPIDLE'):
            self.assertEqual(CONF.wsgi.tcp_keepidle,
                             sock.getsockopt(socket.IPPROTO_TCP,
                                             socket.TCP_KEEPIDLE))
        server.stop()
        server.wait()

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_app_using_ipv6_and_ssl(self):
        greetings = 'Hello, World!!!'

        @webob.dec.wsgify
        def hello_world(req):
            return greetings

        server = nova.wsgi.Server("fake_ssl",
                                  hello_world,
                                  host="::1",
                                  port=0,
                                  use_ssl=True)

        server.start()

        response = requests.get('https://[::1]:%d/' % server.port,
                                verify=os.path.join(SSL_CERT_DIR, 'ca.crt'))
        self.assertEqual(greetings, response.text)

        server.stop()
        server.wait()
