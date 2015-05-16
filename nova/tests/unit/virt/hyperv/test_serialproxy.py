# Copyright 2016 Cloudbase Solutions Srl
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

import socket

import mock

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import serialproxy


class SerialProxyTestCase(test_base.HyperVBaseTestCase):
    @mock.patch.object(socket, 'socket')
    def setUp(self, mock_socket):
        super(SerialProxyTestCase, self).setUp()

        self._mock_socket = mock_socket
        self._mock_input_queue = mock.Mock()
        self._mock_output_queue = mock.Mock()
        self._mock_client_connected = mock.Mock()

        threading_patcher = mock.patch.object(serialproxy, 'threading')
        threading_patcher.start()
        self.addCleanup(threading_patcher.stop)

        self._proxy = serialproxy.SerialProxy(
            mock.sentinel.instance_nane,
            mock.sentinel.host,
            mock.sentinel.port,
            self._mock_input_queue,
            self._mock_output_queue,
            self._mock_client_connected)

    @mock.patch.object(socket, 'socket')
    def test_setup_socket_exception(self, mock_socket):
        fake_socket = mock_socket.return_value

        fake_socket.listen.side_effect = socket.error

        self.assertRaises(exception.NovaException,
                          self._proxy._setup_socket)

        fake_socket.setsockopt.assert_called_once_with(socket.SOL_SOCKET,
                                                       socket.SO_REUSEADDR,
                                                       1)
        fake_socket.bind.assert_called_once_with((mock.sentinel.host,
                                                  mock.sentinel.port))

    def test_stop_serial_proxy(self):
        self._proxy._conn = mock.Mock()
        self._proxy._sock = mock.Mock()

        self._proxy.stop()

        self._proxy._stopped.set.assert_called_once_with()
        self._proxy._client_connected.clear.assert_called_once_with()
        self._proxy._conn.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        self._proxy._conn.close.assert_called_once_with()
        self._proxy._sock.close.assert_called_once_with()

    @mock.patch.object(serialproxy.SerialProxy, '_accept_conn')
    @mock.patch.object(serialproxy.SerialProxy, '_setup_socket')
    def test_run(self, mock_setup_socket, mock_accept_con):
        self._proxy._stopped = mock.MagicMock()
        self._proxy._stopped.isSet.side_effect = [False, True]

        self._proxy.run()

        mock_setup_socket.assert_called_once_with()
        mock_accept_con.assert_called_once_with()

    def test_accept_connection(self):
        mock_conn = mock.Mock()
        self._proxy._sock = mock.Mock()
        self._proxy._sock.accept.return_value = [
            mock_conn, (mock.sentinel.client_addr, mock.sentinel.client_port)]

        self._proxy._accept_conn()

        self._proxy._client_connected.set.assert_called_once_with()
        mock_conn.close.assert_called_once_with()
        self.assertIsNone(self._proxy._conn)

        thread = serialproxy.threading.Thread
        for job in [self._proxy._get_data,
                    self._proxy._send_data]:
            thread.assert_any_call(target=job)

    def test_get_data(self):
        self._mock_client_connected.isSet.return_value = True
        self._proxy._conn = mock.Mock()
        self._proxy._conn.recv.side_effect = [mock.sentinel.data, None]

        self._proxy._get_data()

        self._mock_client_connected.clear.assert_called_once_with()
        self._mock_input_queue.put.assert_called_once_with(mock.sentinel.data)

    def _test_send_data(self, exception=None):
        self._mock_client_connected.isSet.side_effect = [True, False]
        self._mock_output_queue.get_burst.return_value = mock.sentinel.data
        self._proxy._conn = mock.Mock()
        self._proxy._conn.sendall.side_effect = exception

        self._proxy._send_data()

        self._proxy._conn.sendall.assert_called_once_with(
            mock.sentinel.data)

        if exception:
            self._proxy._client_connected.clear.assert_called_once_with()

    def test_send_data(self):
        self._test_send_data()

    def test_send_data_exception(self):
        self._test_send_data(exception=socket.error)
