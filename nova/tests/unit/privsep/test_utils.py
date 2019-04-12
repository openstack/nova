# Copyright 2011 Justin Santa Barbara
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

import errno
import mock
import os

import nova.privsep.utils
from nova import test
from nova.tests import fixtures


class SupportDirectIOTestCase(test.NoDBTestCase):
    def setUp(self):
        super(SupportDirectIOTestCase, self).setUp()
        # O_DIRECT is not supported on all Python runtimes, so on platforms
        # where it's not supported (e.g. Mac), we can still test the code-path
        # by stubbing out the value.
        if not hasattr(os, 'O_DIRECT'):
            # `mock` seems to have trouble stubbing an attr that doesn't
            # originally exist, so falling back to stubbing out the attribute
            # directly.
            os.O_DIRECT = 16384
            self.addCleanup(delattr, os, 'O_DIRECT')
        self.einval = OSError()
        self.einval.errno = errno.EINVAL
        self.enoent = OSError()
        self.enoent.errno = errno.ENOENT
        self.test_path = os.path.join('.', '.directio.test.123')
        self.io_flags = os.O_CREAT | os.O_WRONLY | os.O_DIRECT

        open_patcher = mock.patch('os.open')
        write_patcher = mock.patch('os.write')
        close_patcher = mock.patch('os.close')
        unlink_patcher = mock.patch('os.unlink')
        random_string_patcher = mock.patch(
            'nova.privsep.utils.generate_random_string', return_value='123')
        self.addCleanup(open_patcher.stop)
        self.addCleanup(write_patcher.stop)
        self.addCleanup(close_patcher.stop)
        self.addCleanup(unlink_patcher.stop)
        self.addCleanup(random_string_patcher.stop)
        self.mock_open = open_patcher.start()
        self.mock_write = write_patcher.start()
        self.mock_close = close_patcher.start()
        self.mock_unlink = unlink_patcher.start()
        random_string_patcher.start()

    def test_supports_direct_io(self):
        self.mock_open.return_value = 3

        self.assertTrue(nova.privsep.utils.supports_direct_io('.'))

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_called_once_with(3, mock.ANY)
        # ensure unlink(filepath) will actually remove the file by deleting
        # the remaining link to it in close(fd)
        self.mock_close.assert_called_once_with(3)
        self.mock_unlink.assert_called_once_with(self.test_path)

    def test_supports_direct_io_with_exception_in_write(self):
        self.mock_open.return_value = 3
        self.mock_write.side_effect = ValueError()

        self.assertRaises(ValueError, nova.privsep.utils.supports_direct_io,
                          '.')

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_called_once_with(3, mock.ANY)
        # ensure unlink(filepath) will actually remove the file by deleting
        # the remaining link to it in close(fd)
        self.mock_close.assert_called_once_with(3)
        self.mock_unlink.assert_called_once_with(self.test_path)

    def test_supports_direct_io_with_exception_in_open(self):
        self.mock_open.side_effect = ValueError()

        self.assertRaises(ValueError, nova.privsep.utils.supports_direct_io,
                          '.')

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_not_called()
        self.mock_close.assert_not_called()
        self.mock_unlink.assert_called_once_with(self.test_path)

    def test_supports_direct_io_with_oserror_in_write(self):
        self.mock_open.return_value = 3
        self.mock_write.side_effect = self.einval

        self.assertFalse(nova.privsep.utils.supports_direct_io('.'))

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_called_once_with(3, mock.ANY)
        # ensure unlink(filepath) will actually remove the file by deleting
        # the remaining link to it in close(fd)
        self.mock_close.assert_called_once_with(3)
        self.mock_unlink.assert_called_once_with(self.test_path)

    def test_supports_direct_io_with_oserror_in_open_einval(self):
        self.mock_open.side_effect = self.einval

        self.assertFalse(nova.privsep.utils.supports_direct_io('.'))

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_not_called()
        self.mock_close.assert_not_called()
        self.mock_unlink.assert_called_once_with(self.test_path)

    def test_supports_direct_io_with_oserror_in_open_enoent(self):
        self.mock_open.side_effect = self.enoent

        self.assertFalse(nova.privsep.utils.supports_direct_io('.'))

        self.mock_open.assert_called_once_with(self.test_path, self.io_flags)
        self.mock_write.assert_not_called()
        self.mock_close.assert_not_called()
        self.mock_unlink.assert_called_once_with(self.test_path)


class UtilsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(UtilsTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    @mock.patch('os.kill')
    def test_kill(self, mock_kill):
        nova.privsep.utils.kill(42, -9)
        mock_kill.assert_called_with(42, -9)
