# Copyright 2017,2018 IBM Corp.
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

import mock

from zvmconnector import connector

from nova import exception
from nova import test
from nova.virt.zvm import utils as zvmutils


class TestZVMUtils(test.NoDBTestCase):

    def setUp(self):
        super(TestZVMUtils, self).setUp()
        self.flags(cloud_connector_url='http://127.0.0.1', group='zvm')
        self._url = 'http://127.0.0.1'

    def test_connector_request_handler_invalid_url(self):
        rh = zvmutils.ConnectorClient('http://invalid')
        self.assertRaises(exception.ZVMDriverException, rh.call, 'guest_list')

    @mock.patch('zvmconnector.connector.ZVMConnector.__init__',
                return_value=None)
    def test_connector_request_handler_https(self, mock_init):
        rh = zvmutils.ConnectorClient('https://127.0.0.1:80',
                                      ca_file='/tmp/file')
        mock_init.assert_called_once_with('127.0.0.1', 80, ssl_enabled=True,
                                          verify='/tmp/file')
        self.assertIsInstance(rh._conn, connector.ZVMConnector)

    @mock.patch('zvmconnector.connector.ZVMConnector.__init__',
                return_value=None)
    def test_connector_request_handler_https_noca(self, mock_init):
        rh = zvmutils.ConnectorClient('https://127.0.0.1:80')
        mock_init.assert_called_once_with('127.0.0.1', 80, ssl_enabled=True,
                                          verify=False)
        self.assertIsInstance(rh._conn, connector.ZVMConnector)

    @mock.patch('zvmconnector.connector.ZVMConnector.__init__',
                return_value=None)
    def test_connector_request_handler_http(self, mock_init):
        rh = zvmutils.ConnectorClient('http://127.0.0.1:80')
        mock_init.assert_called_once_with('127.0.0.1', 80, ssl_enabled=False,
                                          verify=False)
        self.assertIsInstance(rh._conn, connector.ZVMConnector)

    @mock.patch('zvmconnector.connector.ZVMConnector.send_request')
    def test_connector_request_handler(self, mock_send):
        mock_send.return_value = {'overallRC': 0, 'output': 'data',
                                  'rc': 0, 'rs': 0}
        rh = zvmutils.ConnectorClient(self._url)
        res = rh.call('guest_list')
        self.assertEqual('data', res)

    @mock.patch('zvmconnector.connector.ZVMConnector.send_request')
    def test_connector_request_handler_error(self, mock_send):
        expected = {'overallRC': 1, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        mock_send.return_value = expected

        rh = zvmutils.ConnectorClient(self._url)
        exc = self.assertRaises(exception.ZVMConnectorError, rh.call,
                                'guest_list')
        self.assertIn('zVM Cloud Connector request failed',
                      exc.format_message())
        self.assertEqual(expected['overallRC'], exc.overallRC)
        self.assertEqual(expected['rc'], exc.rc)
        self.assertEqual(expected['rs'], exc.rs)
        self.assertEqual(expected['errmsg'], exc.errmsg)
