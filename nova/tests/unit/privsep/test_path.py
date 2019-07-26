# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
# Copyright 2019 Aptira Pty Ltd
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
import os
import six
import tempfile

from nova import exception
import nova.privsep.path
from nova import test
from nova.tests import fixtures


class FileTestCase(test.NoDBTestCase):
    """Test file related utility methods."""

    def setUp(self):
        super(FileTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    @mock.patch('os.path.exists', return_value=True)
    def test_readfile(self, mock_exists):
        mock_open = mock.mock_open(read_data='hello world')
        with mock.patch.object(six.moves.builtins, 'open',
                               new=mock_open):
            self.assertEqual('hello world',
                             nova.privsep.path.readfile('/fake/path'))

    @mock.patch('os.path.exists', return_value=False)
    def test_readfile_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.readfile,
                          '/fake/path')

    @mock.patch('os.path.exists', return_value=True)
    def test_write(self, mock_exists):
        mock_open = mock.mock_open()
        with mock.patch.object(six.moves.builtins, 'open',
                               new=mock_open):
            nova.privsep.path.writefile('/fake/path/file', 'w', 'foo')

        handle = mock_open()
        mock_exists.assert_called_with('/fake/path')
        self.assertTrue(mock.call('/fake/path/file', 'w') in
                        mock_open.mock_calls)
        handle.write.assert_called_with('foo')

    @mock.patch('os.path.exists', return_value=False)
    def test_write_dir_missing(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.writefile,
                          '/fake/path', 'w', 'foo')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.readlink')
    def test_readlink(self, mock_readlink, mock_exists):
        nova.privsep.path.readlink('/fake/path')
        mock_exists.assert_called_with('/fake/path')
        mock_readlink.assert_called_with('/fake/path')

    @mock.patch('os.path.exists', return_value=False)
    def test_readlink_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.readlink,
                          '/fake/path')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.chown')
    def test_chown(self, mock_chown, mock_exists):
        nova.privsep.path.chown('/fake/path', uid=42, gid=43)
        mock_exists.assert_called_with('/fake/path')
        mock_chown.assert_called_with('/fake/path', 42, 43)

    @mock.patch('os.path.exists', return_value=False)
    def test_chown_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.chown,
                          '/fake/path')

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    def test_makedirs(self, mock_ensure_tree):
        nova.privsep.path.makedirs('/fake/path')
        mock_ensure_tree.assert_called_with('/fake/path')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.chmod')
    def test_chmod(self, mock_chmod, mock_exists):
        nova.privsep.path.chmod('/fake/path', 0x666)
        mock_exists.assert_called_with('/fake/path')
        mock_chmod.assert_called_with('/fake/path', 0x666)

    @mock.patch('os.path.exists', return_value=False)
    def test_chmod_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.chmod,
                          '/fake/path', 0x666)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.utime')
    def test_utime(self, mock_utime, mock_exists):
        nova.privsep.path.utime('/fake/path')
        mock_exists.assert_called_with('/fake/path')
        mock_utime.assert_called_with('/fake/path', None)

    @mock.patch('os.path.exists', return_value=False)
    def test_utime_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.utime,
                          '/fake/path')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.rmdir')
    def test_rmdir(self, mock_rmdir, mock_exists):
        nova.privsep.path.rmdir('/fake/path')
        mock_exists.assert_called_with('/fake/path')
        mock_rmdir.assert_called_with('/fake/path')

    @mock.patch('os.path.exists', return_value=False)
    def test_rmdir_file_not_found(self, mock_exists):
        self.assertRaises(exception.FileNotFound,
                          nova.privsep.path.rmdir,
                          '/fake/path')

    @mock.patch('os.path.exists', return_value=True)
    def test_exists(self, mock_exists):
        nova.privsep.path.path.exists('/fake/path')
        mock_exists.assert_called_with('/fake/path')


class LastBytesTestCase(test.NoDBTestCase):
    """Test the last_bytes() utility method."""

    def setUp(self):
        super(LastBytesTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    def test_truncated(self):
        try:
            fd, path = tempfile.mkstemp()
            os.write(fd, b'1234567890')
            os.close(fd)

            out, remaining = nova.privsep.path.last_bytes(path, 5)
            self.assertEqual(out, b'67890')
            self.assertGreater(remaining, 0)

        finally:
            os.unlink(path)

    def test_read_all(self):
        try:
            fd, path = tempfile.mkstemp()
            os.write(fd, b'1234567890')
            os.close(fd)

            out, remaining = nova.privsep.path.last_bytes(path, 1000)
            self.assertEqual(out, b'1234567890')
            self.assertFalse(remaining > 0)

        finally:
            os.unlink(path)
