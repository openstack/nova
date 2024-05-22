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

import io
import os
from unittest import mock

from nova import exception
from nova import filesystem
from nova import test


class TestFSCommon(test.NoDBTestCase):

    def test_read_sys(self):
        open_mock = mock.mock_open(read_data='bar')
        with mock.patch('builtins.open', open_mock) as m_open:
            self.assertEqual('bar', filesystem.read_sys('foo'))
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_called_once_with(expected_path, mode='r')

    def test_read_sys_error(self):
        with mock.patch('builtins.open',
                        side_effect=OSError('error')) as m_open:
            self.assertRaises(exception.FileNotFound,
                              filesystem.read_sys, 'foo')
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_called_once_with(expected_path, mode='r')

    def test_read_sys_retry(self):
        open_mock = mock.mock_open()
        with mock.patch('builtins.open', open_mock) as m_open:
            m_open.side_effect = [
                OSError(16, 'Device or resource busy'),
                io.StringIO('bar'),
            ]
            self.assertEqual('bar', filesystem.read_sys('foo'))
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_has_calls([
            mock.call(expected_path, mode='r'),
            mock.call(expected_path, mode='r'),
        ])

    def test_read_sys_retry_limit(self):
        open_mock = mock.mock_open()
        with mock.patch('builtins.open', open_mock) as m_open:
            m_open.side_effect = (
                [OSError(16, 'Device or resource busy')] *
                (filesystem.RETRY_LIMIT + 1))
            self.assertRaises(
                exception.DeviceBusy, filesystem.read_sys, 'foo')

    def test_write_sys(self):
        open_mock = mock.mock_open()
        with mock.patch('builtins.open', open_mock) as m_open:
            self.assertIsNone(filesystem.write_sys('foo', 'bar'))
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_called_once_with(expected_path, mode='w')
        open_mock().write.assert_called_once_with('bar')

    def test_write_sys_error(self):
        with mock.patch('builtins.open',
                        side_effect=OSError('fake_error')) as m_open:
            self.assertRaises(exception.FileNotFound,
                              filesystem.write_sys, 'foo', 'bar')
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_called_once_with(expected_path, mode='w')

    def test_write_sys_retry(self):
        open_mock = mock.mock_open()
        with mock.patch('builtins.open', open_mock) as m_open:
            m_open.side_effect = [
                OSError(16, 'Device or resource busy'),
                io.StringIO(),
            ]
            self.assertIsNone(filesystem.write_sys('foo', 'bar'))
        expected_path = os.path.join(filesystem.SYS, 'foo')
        m_open.assert_has_calls([
            mock.call(expected_path, mode='w'),
            mock.call(expected_path, mode='w'),
        ])

    def test_write_sys_retry_limit(self):
        open_mock = mock.mock_open()
        with mock.patch('builtins.open', open_mock) as m_open:
            m_open.side_effect = (
                [OSError(16, 'Device or resource busy')] *
                (filesystem.RETRY_LIMIT + 1))
            self.assertRaises(
                exception.DeviceBusy, filesystem.write_sys, 'foo', 'bar')
