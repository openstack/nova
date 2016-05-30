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

import tempfile

import mock
from oslo_concurrency import processutils

from nova import exception
from nova import test
from nova.tests.unit import utils as tests_utils
import nova.utils
from nova.virt.disk.mount import nbd
from nova.virt.disk.vfs import localfs as vfsimpl
from nova.virt.image import model as imgmodel


dirs = []
files = {}
commands = []


def fake_execute(*args, **kwargs):
    commands.append({"args": args, "kwargs": kwargs})

    if args[0] == "readlink":
        if args[1] == "-nm":
            if args[2] in ["/scratch/dir/some/file",
                           "/scratch/dir/some/dir",
                           "/scratch/dir/other/dir",
                           "/scratch/dir/other/file"]:
                return args[2], ""
        elif args[1] == "-e":
            if args[2] in files:
                return args[2], ""

        return "", "No such file"
    elif args[0] == "mkdir":
        dirs.append(args[2])
    elif args[0] == "chown":
        owner = args[1]
        path = args[2]
        if path not in files:
            raise Exception("No such file: " + path)

        sep = owner.find(':')
        if sep != -1:
            user = owner[0:sep]
            group = owner[sep + 1:]
        else:
            user = owner
            group = None

        if user:
            if user == "fred":
                uid = 105
            else:
                uid = 110
            files[path]["uid"] = uid
        if group:
            if group == "users":
                gid = 500
            else:
                gid = 600
            files[path]["gid"] = gid
    elif args[0] == "chgrp":
        group = args[1]
        path = args[2]
        if path not in files:
            raise Exception("No such file: " + path)

        if group == "users":
            gid = 500
        else:
            gid = 600
        files[path]["gid"] = gid
    elif args[0] == "chmod":
        mode = args[1]
        path = args[2]
        if path not in files:
            raise Exception("No such file: " + path)

        files[path]["mode"] = int(mode, 8)
    elif args[0] == "cat":
        path = args[1]
        if path not in files:
            files[path] = {
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0o700
                }
        return files[path]["content"], ""
    elif args[0] == "tee":
        if args[1] == "-a":
            path = args[2]
            append = True
        else:
            path = args[1]
            append = False
        if path not in files:
            files[path] = {
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0o700,
                }
        if append:
            files[path]["content"] += kwargs["process_input"]
        else:
            files[path]["content"] = kwargs["process_input"]


class VirtDiskVFSLocalFSTestPaths(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSLocalFSTestPaths, self).setUp()

        real_execute = processutils.execute

        def nonroot_execute(*cmd_parts, **kwargs):
            kwargs.pop('run_as_root', None)
            return real_execute(*cmd_parts, **kwargs)

        self.stub_out('oslo_concurrency.processutils.execute', nonroot_execute)
        self.rawfile = imgmodel.LocalFileImage("/dummy.img",
                                               imgmodel.FORMAT_RAW)

    def test_check_safe_path(self):
        if not tests_utils.coreutils_readlink_available():
            self.skipTest("coreutils readlink(1) unavailable")
        vfs = vfsimpl.VFSLocalFS(self.rawfile)
        vfs.imgdir = "/foo"
        ret = vfs._canonical_path('etc/something.conf')
        self.assertEqual(ret, '/foo/etc/something.conf')

    def test_check_unsafe_path(self):
        if not tests_utils.coreutils_readlink_available():
            self.skipTest("coreutils readlink(1) unavailable")
        vfs = vfsimpl.VFSLocalFS(self.rawfile)
        vfs.imgdir = "/foo"
        self.assertRaises(exception.Invalid,
                          vfs._canonical_path,
                          'etc/../../../something.conf')


class VirtDiskVFSLocalFSTest(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSLocalFSTest, self).setUp()

        self.qcowfile = imgmodel.LocalFileImage("/dummy.qcow2",
                                                imgmodel.FORMAT_QCOW2)
        self.rawfile = imgmodel.LocalFileImage("/dummy.img",
                                               imgmodel.FORMAT_RAW)

    def test_makepath(self):
        global dirs, commands
        dirs = []
        commands = []
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.make_path("/some/dir")
        vfs.make_path("/other/dir")

        self.assertEqual(dirs,
                         ["/scratch/dir/some/dir", "/scratch/dir/other/dir"]),

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/dir'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('mkdir', '-p',
                                    '/scratch/dir/some/dir'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/other/dir'),
                            'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('mkdir', '-p',
                                    '/scratch/dir/other/dir'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}}])

    def test_append_file(self):
        global files, commands
        files = {}
        commands = []
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.append_file("/some/file", " Goodbye")

        self.assertIn("/scratch/dir/some/file", files)
        self.assertEqual(files["/scratch/dir/some/file"]["content"],
                         "Hello World Goodbye")

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('tee', '-a',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'process_input': ' Goodbye',
                                      'run_as_root': True,
                                      'root_helper': root_helper}}])

    def test_replace_file(self):
        global files, commands
        files = {}
        commands = []
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.replace_file("/some/file", "Goodbye")

        self.assertIn("/scratch/dir/some/file", files)
        self.assertEqual(files["/scratch/dir/some/file"]["content"],
                         "Goodbye")

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('tee', '/scratch/dir/some/file'),
                           'kwargs': {'process_input': 'Goodbye',
                                      'run_as_root': True,
                                      'root_helper': root_helper}}])

    def test_read_file(self):
        global commands, files
        files = {}
        commands = []
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        self.assertEqual(vfs.read_file("/some/file"), "Hello World")

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}}])

    def test_has_file(self):
        global commands, files
        files = {}
        commands = []
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        self.assertTrue(vfs.has_file("/some/file"))
        self.assertFalse(vfs.has_file("/other/file"))

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-e',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/other/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-e',
                                    '/scratch/dir/other/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          ])

    def test_set_permissions(self):
        global commands, files
        commands = []
        files = {}
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        vfs.set_permissions("/some/file", 0o777)
        self.assertEqual(files["/scratch/dir/some/file"]["mode"], 0o777)

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('chmod', '777',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}}])

    def test_set_ownership(self):
        global commands, files
        commands = []
        files = {}
        self.stub_out('oslo_concurrency.processutils.execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(self.qcowfile)
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        self.assertEqual(files["/scratch/dir/some/file"]["uid"], 100)
        self.assertEqual(files["/scratch/dir/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", "fred", None)
        self.assertEqual(files["/scratch/dir/some/file"]["uid"], 105)
        self.assertEqual(files["/scratch/dir/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", None, "users")
        self.assertEqual(files["/scratch/dir/some/file"]["uid"], 105)
        self.assertEqual(files["/scratch/dir/some/file"]["gid"], 500)

        vfs.set_ownership("/some/file", "joe", "admins")
        self.assertEqual(files["/scratch/dir/some/file"]["uid"], 110)
        self.assertEqual(files["/scratch/dir/some/file"]["gid"], 600)

        root_helper = nova.utils.get_root_helper()
        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('chown', 'fred',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('chgrp', 'users',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}},
                          {'args': ('chown', 'joe:admins',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True,
                                      'root_helper': root_helper}}])

    @mock.patch.object(nova.utils, 'execute')
    def test_get_format_fs(self, execute):
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
        execute.return_value = ('ext3\n', '')

        vfs.setup()
        self.assertEqual('ext3', vfs.get_image_fs())
        vfs.teardown()
        vfs.mount.get_dev.assert_called_once_with()
        execute.assert_called_once_with('blkid', '-o',
                                        'value', '-s',
                                        'TYPE', '/dev/xyz',
                                        run_as_root=True,
                                        check_exit_code=[0, 2])

    @mock.patch.object(tempfile, 'mkdtemp')
    @mock.patch.object(nbd, 'NbdMount')
    def test_setup_mount(self, NbdMount, mkdtemp):
        vfs = vfsimpl.VFSLocalFS(self.qcowfile)

        mounter = mock.MagicMock()
        mkdtemp.return_value = 'tmp/'
        NbdMount.return_value = mounter

        vfs.setup()

        self.assertTrue(mkdtemp.called)
        NbdMount.assert_called_once_with(self.qcowfile, "tmp/", None)
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
        NbdMount.assert_called_once_with(self.qcowfile, "tmp/", None)
        self.assertFalse(mounter.do_mount.called)
