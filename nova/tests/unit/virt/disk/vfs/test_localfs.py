#    Copyright (C) 2012 Red Hat, Inc.
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

import grp
import pwd
import tempfile

from collections import namedtuple
import mock

from nova import exception
from nova import test
import nova.utils
from nova.virt.disk.mount import nbd
from nova.virt.disk.vfs import localfs as vfsimpl
from nova.virt.image import model as imgmodel


class VirtDiskVFSLocalFSTestPaths(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSLocalFSTestPaths, self).setUp()

        self.rawfile = imgmodel.LocalFileImage('/dummy.img',
                                               imgmodel.FORMAT_RAW)

    # NOTE(mikal): mocking a decorator is non-trivial, so this is the
    # best we can do.

    @mock.patch.object(nova.privsep.path, 'readlink')
    def test_check_safe_path(self, read_link):
        vfs = vfsimpl.VFSLocalFS(self.rawfile)
        vfs.imgdir = '/foo'

        read_link.return_value = '/foo/etc/something.conf'

        ret = vfs._canonical_path('etc/something.conf')
        self.assertEqual(ret, '/foo/etc/something.conf')

    @mock.patch.object(nova.privsep.path, 'readlink')
    def test_check_unsafe_path(self, read_link):
        vfs = vfsimpl.VFSLocalFS(self.rawfile)
        vfs.imgdir = '/foo'

        read_link.return_value = '/etc/something.conf'

        self.assertRaises(exception.Invalid,
                          vfs._canonical_path,
                          'etc/../../../something.conf')


class VirtDiskVFSLocalFSTest(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSLocalFSTest, self).setUp()

        self.qcowfile = imgmodel.LocalFileImage('/dummy.qcow2',
                                                imgmodel.FORMAT_QCOW2)
        self.rawfile = imgmodel.LocalFileImage('/dummy.img',
                                               imgmodel.FORMAT_RAW)

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'makedirs')
    def test_makepath(self, mkdir, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        vfs.make_path('/some/dir')
        read_link.assert_called()
        mkdir.assert_called_with(read_link.return_value)

        read_link.reset_mock()
        mkdir.reset_mock()
        vfs.make_path('/other/dir')
        read_link.assert_called()
        mkdir.assert_called_with(read_link.return_value)

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'writefile')
    def test_append_file(self, write_file, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        vfs.append_file('/some/file', ' Goodbye')

        read_link.assert_called()
        write_file.assert_called_with(read_link.return_value, 'a', ' Goodbye')

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'writefile')
    def test_replace_file(self, write_file, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        vfs.replace_file('/some/file', 'Goodbye')

        read_link.assert_called()
        write_file.assert_called_with(read_link.return_value, 'w', 'Goodbye')

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'readfile')
    def test_read_file(self, read_file, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        self.assertEqual(read_file.return_value, vfs.read_file('/some/file'))
        read_link.assert_called()
        read_file.assert_called()

    @mock.patch.object(nova.privsep.path.path, 'exists')
    def test_has_file(self, exists):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'
        has = vfs.has_file('/some/file')
        self.assertEqual(exists.return_value, has)

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'chmod')
    def test_set_permissions(self, chmod, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        vfs.set_permissions('/some/file', 0o777)
        read_link.assert_called()
        chmod.assert_called_with(read_link.return_value, 0o777)

    @mock.patch.object(nova.privsep.path, 'readlink')
    @mock.patch.object(nova.privsep.path, 'chown')
    @mock.patch.object(pwd, 'getpwnam')
    @mock.patch.object(grp, 'getgrnam')
    def test_set_ownership(self, getgrnam, getpwnam, chown, read_link):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = '/scratch/dir'

        fake_passwd = namedtuple('fake_passwd', 'pw_uid')
        getpwnam.return_value(fake_passwd(pw_uid=100))

        fake_group = namedtuple('fake_group', 'gr_gid')
        getgrnam.return_value(fake_group(gr_gid=101))

        vfs.set_ownership('/some/file', 'fred', None)
        read_link.assert_called()
        chown.assert_called_with(read_link.return_value,
                                 uid=getpwnam.return_value.pw_uid)

        read_link.reset_mock()
        chown.reset_mock()
        vfs.set_ownership('/some/file', None, 'users')
        read_link.assert_called()
        chown.assert_called_with(read_link.return_value,
                                 gid=getgrnam.return_value.gr_gid)

        read_link.reset_mock()
        chown.reset_mock()
        vfs.set_ownership('/some/file', 'joe', 'admins')
        read_link.assert_called()
        chown.assert_called_with(read_link.return_value,
                                 uid=getpwnam.return_value.pw_uid,
                                 gid=getgrnam.return_value.gr_gid)

    @mock.patch('nova.privsep.fs.get_filesystem_type',
                return_value=('ext3\n', ''))
    def test_get_format_fs(self, mock_type):
        vfs = vfsimpl.VFSLocalFS(self.rawfile)
        vfs.setup = mock.MagicMock()
        vfs.teardown = mock.MagicMock()

        def fake_setup():
            vfs.mount = mock.MagicMock()
            vfs.mount.device = None
            vfs.mount.get_dev.side_effect = fake_get_dev

        def fake_teardown():
            vfs.mount.device = None

        def fake_get_dev():
            vfs.mount.device = '/dev/xyz'
            return True

        vfs.setup.side_effect = fake_setup
        vfs.teardown.side_effect = fake_teardown

        vfs.setup()
        self.assertEqual('ext3', vfs.get_image_fs())
        vfs.teardown()
        vfs.mount.get_dev.assert_called_once_with()
        mock_type.assert_called_once_with('/dev/xyz')

    @mock.patch.object(tempfile, 'mkdtemp')
    @mock.patch.object(nbd, 'NbdMount')
    def test_setup_mount(self, NbdMount, mkdtemp):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)

        mounter = mock.MagicMock()
        mkdtemp.return_value = 'tmp/'
        NbdMount.return_value = mounter

        vfs.setup()

        self.assertTrue(mkdtemp.called)
        NbdMount.assert_called_once_with(self.qcowfile, 'tmp/', None)
        mounter.do_mount.assert_called_once_with()

    @mock.patch.object(tempfile, 'mkdtemp')
    @mock.patch.object(nbd, 'NbdMount')
    def test_setup_mount_false(self, NbdMount, mkdtemp):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)

        mounter = mock.MagicMock()
        mkdtemp.return_value = 'tmp/'
        NbdMount.return_value = mounter

        vfs.setup(mount=False)

        self.assertTrue(mkdtemp.called)
        NbdMount.assert_called_once_with(self.qcowfile, 'tmp/', None)
        self.assertFalse(mounter.do_mount.called)
