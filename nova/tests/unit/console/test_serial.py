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

"""Tests for Serial Console."""

import socket

import mock
import six.moves

from nova.console import serial
from nova import exception
from nova import test


class SerialTestCase(test.NoDBTestCase):
    def setUp(self):
        super(SerialTestCase, self).setUp()
        serial.ALLOCATED_PORTS = set()

    def test_get_port_range(self):
        start, stop = serial._get_port_range()
        self.assertEqual(10000, start)
        self.assertEqual(20000, stop)

    def test_get_port_range_customized(self):
        self.flags(port_range='30000:40000', group='serial_console')
        start, stop = serial._get_port_range()
        self.assertEqual(30000, start)
        self.assertEqual(40000, stop)

    def test_get_port_range_bad_range(self):
        self.flags(port_range='40000:30000', group='serial_console')
        start, stop = serial._get_port_range()
        self.assertEqual(10000, start)
        self.assertEqual(20000, stop)

    @mock.patch('socket.socket')
    def test_verify_port(self, fake_socket):
        s = mock.MagicMock()
        fake_socket.return_value = s

        serial._verify_port('127.0.0.1', 10)

        s.bind.assert_called_once_with(('127.0.0.1', 10))

    @mock.patch('socket.socket')
    def test_verify_port_in_use(self, fake_socket):
        s = mock.MagicMock()
        s.bind.side_effect = socket.error()
        fake_socket.return_value = s

        self.assertRaises(
            exception.SocketPortInUseException,
            serial._verify_port, '127.0.0.1', 10)

        s.bind.assert_called_once_with(('127.0.0.1', 10))

    @mock.patch('nova.console.serial._verify_port', lambda x, y: None)
    def test_acquire_port(self):
        start, stop = 15, 20
        self.flags(
            port_range='%d:%d' % (start, stop),
            group='serial_console')

        for port in six.moves.range(start, stop):
            self.assertEqual(port, serial.acquire_port('127.0.0.1'))

        for port in six.moves.range(start, stop):
            self.assertEqual(port, serial.acquire_port('127.0.0.2'))

        self.assertEqual(10, len(serial.ALLOCATED_PORTS))

    @mock.patch('nova.console.serial._verify_port')
    def test_acquire_port_in_use(self, fake_verify_port):
        def port_10000_already_used(host, port):
            if port == 10000 and host == '127.0.0.1':
                raise exception.SocketPortInUseException(
                    port=port,
                    host=host,
                    error="already in use")
        fake_verify_port.side_effect = port_10000_already_used

        self.assertEqual(10001, serial.acquire_port('127.0.0.1'))
        self.assertEqual(10000, serial.acquire_port('127.0.0.2'))

        self.assertNotIn(('127.0.0.1', 10000), serial.ALLOCATED_PORTS)
        self.assertIn(('127.0.0.1', 10001), serial.ALLOCATED_PORTS)
        self.assertIn(('127.0.0.2', 10000), serial.ALLOCATED_PORTS)

    @mock.patch('nova.console.serial._verify_port')
    def test_acquire_port_not_ble_to_bind_at_any_port(self, fake_verify_port):
        start, stop = 15, 20
        self.flags(
            port_range='%d:%d' % (start, stop),
            group='serial_console')

        fake_verify_port.side_effect = (
            exception.SocketPortRangeExhaustedException(host='127.0.0.1'))

        self.assertRaises(
            exception.SocketPortRangeExhaustedException,
            serial.acquire_port, '127.0.0.1')

    def test_release_port(self):
        serial.ALLOCATED_PORTS.add(('127.0.0.1', 100))
        serial.ALLOCATED_PORTS.add(('127.0.0.2', 100))
        self.assertEqual(2, len(serial.ALLOCATED_PORTS))

        serial.release_port('127.0.0.1', 100)
        self.assertEqual(1, len(serial.ALLOCATED_PORTS))

        serial.release_port('127.0.0.2', 100)
        self.assertEqual(0, len(serial.ALLOCATED_PORTS))
