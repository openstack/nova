# Copyright 2015 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import fixtures
import mock
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from six.moves import StringIO

from nova.cmd import baseproxy
from nova import config
from nova.console import websocketproxy
from nova import test
from nova import version


@mock.patch.object(config, 'parse_args', new=lambda *args, **kwargs: None)
class BaseProxyTestCase(test.NoDBTestCase):

    def setUp(self):
        super(BaseProxyTestCase, self).setUp()
        self.stderr = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stderr', self.stderr))

    @mock.patch('os.path.exists', return_value=False)
    # NOTE(mriedem): sys.exit raises TestingException so we can actually exit
    # the test normally.
    @mock.patch('sys.exit', side_effect=test.TestingException)
    def test_proxy_ssl_without_cert(self, mock_exit, mock_exists):
        self.flags(ssl_only=True)
        self.assertRaises(test.TestingException, baseproxy.proxy,
                          '0.0.0.0', '6080')
        mock_exit.assert_called_once_with(-1)
        self.assertEqual(self.stderr.getvalue(),
                         "SSL only and self.pem not found\n")

    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('sys.exit', side_effect=test.TestingException)
    def test_proxy_web_dir_does_not_exist(self, mock_exit, mock_exists):
        self.flags(web='/my/fake/webserver/')
        self.assertRaises(test.TestingException, baseproxy.proxy,
                          '0.0.0.0', '6080')
        mock_exit.assert_called_once_with(-1)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch.object(logging, 'setup')
    @mock.patch.object(gmr.TextGuruMeditation, 'setup_autorun')
    @mock.patch('nova.console.websocketproxy.NovaWebSocketProxy.__init__',
                return_value=None)
    @mock.patch('nova.console.websocketproxy.NovaWebSocketProxy.start_server')
    @mock.patch('websockify.websocketproxy.select_ssl_version',
                return_value=None)
    def test_proxy(self, mock_select_ssl_version, mock_start, mock_init,
                   mock_gmr, mock_log, mock_exists):
        baseproxy.proxy('0.0.0.0', '6080')
        mock_log.assert_called_once_with(baseproxy.CONF, 'nova')
        mock_gmr.assert_called_once_with(version, conf=baseproxy.CONF)
        mock_init.assert_called_once_with(
            listen_host='0.0.0.0', listen_port='6080', source_is_ipv6=False,
            cert='self.pem', key=None, ssl_only=False, ssl_ciphers=None,
            ssl_minimum_version='default', daemon=False, record=None,
            security_proxy=None, traffic=True,
            web='/usr/share/spice-html5', file_only=True,
            RequestHandlerClass=websocketproxy.NovaProxyRequestHandler)
        mock_start.assert_called_once_with()

    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('sys.exit', side_effect=test.TestingException)
    def test_proxy_exit_with_error(self, mock_exit, mock_exists):
        self.flags(ssl_only=True)
        self.assertRaises(test.TestingException, baseproxy.proxy,
                          '0.0.0.0', '6080')
        self.assertEqual(self.stderr.getvalue(),
                         "SSL only and self.pem not found\n")
        mock_exit.assert_called_once_with(-1)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.console.websocketproxy.NovaWebSocketProxy.__init__',
                return_value=None)
    @mock.patch('nova.console.websocketproxy.NovaWebSocketProxy.start_server')
    def test_proxy_ssl_settings(self, mock_start, mock_init, mock_exists):
        self.flags(ssl_minimum_version='tlsv1_3', group='console')
        self.flags(ssl_ciphers='ALL:!aNULL', group='console')
        baseproxy.proxy('0.0.0.0', '6080')
        mock_init.assert_called_once_with(
            listen_host='0.0.0.0', listen_port='6080', source_is_ipv6=False,
            cert='self.pem', key=None, ssl_only=False,
            ssl_ciphers='ALL:!aNULL', ssl_minimum_version='tlsv1_3',
            daemon=False, record=None, security_proxy=None, traffic=True,
            web='/usr/share/spice-html5', file_only=True,
            RequestHandlerClass=websocketproxy.NovaProxyRequestHandler)
