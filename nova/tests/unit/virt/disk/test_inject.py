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

from collections import OrderedDict
import os

import fixtures

from nova import exception
from nova import test
from nova.tests.unit.virt.disk.vfs import fakeguestfs
from nova.virt.disk import api as diskapi
from nova.virt.disk.vfs import guestfs as vfsguestfs
from nova.virt.image import model as imgmodel


class VirtDiskTest(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskTest, self).setUp()
        self.useFixture(
                fixtures.MonkeyPatch('nova.virt.disk.vfs.guestfs.guestfs',
                                     fakeguestfs))
        self.file = imgmodel.LocalFileImage("/some/file",
                                            imgmodel.FORMAT_QCOW2)

    def test_inject_data(self):
        self.assertTrue(diskapi.inject_data(
            imgmodel.LocalFileImage("/some/file", imgmodel.FORMAT_QCOW2)))

        self.assertTrue(diskapi.inject_data(
            imgmodel.LocalFileImage("/some/file", imgmodel.FORMAT_RAW),
            mandatory=('files',)))

        self.assertTrue(diskapi.inject_data(
            imgmodel.LocalFileImage("/some/file", imgmodel.FORMAT_RAW),
            key="mysshkey",
            mandatory=('key',)))

        os_name = os.name
        os.name = 'nt'  # Cause password injection to fail
        self.assertRaises(exception.NovaException,
                          diskapi.inject_data,
                          imgmodel.LocalFileImage("/some/file",
                                                  imgmodel.FORMAT_RAW),
                          admin_password="p",
                          mandatory=('admin_password',))
        self.assertFalse(diskapi.inject_data(
            imgmodel.LocalFileImage("/some/file", imgmodel.FORMAT_RAW),
            admin_password="p"))
        os.name = os_name

        self.assertFalse(diskapi.inject_data(
            imgmodel.LocalFileImage("/some/fail/file", imgmodel.FORMAT_RAW),
            key="mysshkey"))

    def test_inject_data_key(self):

        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        diskapi._inject_key_into_fs("mysshkey", vfs)

        self.assertIn("/root/.ssh", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/root/.ssh"],
                         {'isdir': True, 'gid': 0, 'uid': 0, 'mode': 0o700})
        self.assertIn("/root/.ssh/authorized_keys", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/root/.ssh/authorized_keys"],
                         {'isdir': False,
                          'content': "Hello World\n# The following ssh " +
                                     "key was injected by Nova\nmysshkey\n",
                          'gid': 100,
                          'uid': 100,
                          'mode': 0o600})

        vfs.teardown()

    def test_inject_data_key_with_selinux(self):

        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        vfs.make_path("etc/selinux")
        vfs.make_path("etc/rc.d")
        diskapi._inject_key_into_fs("mysshkey", vfs)

        self.assertIn("/etc/rc.d/rc.local", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/etc/rc.d/rc.local"],
                         {'isdir': False,
                          'content': "Hello World#!/bin/sh\n# Added by " +
                                     "Nova to ensure injected ssh keys " +
                                     "have the right context\nrestorecon " +
                                     "-RF root/.ssh 2>/dev/null || :\n",
                          'gid': 100,
                          'uid': 100,
                          'mode': 0o700})

        self.assertIn("/root/.ssh", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/root/.ssh"],
                         {'isdir': True, 'gid': 0, 'uid': 0, 'mode': 0o700})
        self.assertIn("/root/.ssh/authorized_keys", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/root/.ssh/authorized_keys"],
                         {'isdir': False,
                          'content': "Hello World\n# The following ssh " +
                                     "key was injected by Nova\nmysshkey\n",
                          'gid': 100,
                          'uid': 100,
                          'mode': 0o600})

        vfs.teardown()

    def test_inject_data_key_with_selinux_append_with_newline(self):

        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        vfs.replace_file("/etc/rc.d/rc.local", "#!/bin/sh\necho done")
        vfs.make_path("etc/selinux")
        vfs.make_path("etc/rc.d")
        diskapi._inject_key_into_fs("mysshkey", vfs)

        self.assertIn("/etc/rc.d/rc.local", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/etc/rc.d/rc.local"],
                {'isdir': False,
                 'content': "#!/bin/sh\necho done\n# Added "
                            "by Nova to ensure injected ssh keys have "
                            "the right context\nrestorecon -RF "
                            "root/.ssh 2>/dev/null || :\n",
                 'gid': 100,
                 'uid': 100,
                 'mode': 0o700})
        vfs.teardown()

    def test_inject_net(self):

        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        diskapi._inject_net_into_fs("mynetconfig", vfs)

        self.assertIn("/etc/network/interfaces", vfs.handle.files)
        self.assertEqual(vfs.handle.files["/etc/network/interfaces"],
                         {'content': 'mynetconfig',
                          'gid': 100,
                          'isdir': False,
                          'mode': 0o700,
                          'uid': 100})
        vfs.teardown()

    def test_inject_metadata(self):
        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()
        metadata = {"foo": "bar", "eek": "wizz"}
        metadata = OrderedDict(sorted(metadata.items()))
        diskapi._inject_metadata_into_fs(metadata, vfs)

        self.assertIn("/meta.js", vfs.handle.files)
        self.assertEqual({'content': '{"eek": "wizz", ' +
                                     '"foo": "bar"}',
                          'gid': 100,
                          'isdir': False,
                          'mode': 0o700,
                          'uid': 100},
                         vfs.handle.files["/meta.js"])
        vfs.teardown()

    def test_inject_admin_password(self):
        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        def fake_salt():
            return "1234567890abcdef"

        self.stub_out('nova.virt.disk.api._generate_salt', fake_salt)

        vfs.handle.write("/etc/shadow",
                         "root:$1$12345678$xxxxx:14917:0:99999:7:::\n" +
                         "bin:*:14495:0:99999:7:::\n" +
                         "daemon:*:14495:0:99999:7:::\n")

        vfs.handle.write("/etc/passwd",
                         "root:x:0:0:root:/root:/bin/bash\n" +
                         "bin:x:1:1:bin:/bin:/sbin/nologin\n" +
                         "daemon:x:2:2:daemon:/sbin:/sbin/nologin\n")

        diskapi._inject_admin_password_into_fs("123456", vfs)

        self.assertEqual(vfs.handle.files["/etc/passwd"],
                         {'content': "root:x:0:0:root:/root:/bin/bash\n" +
                                     "bin:x:1:1:bin:/bin:/sbin/nologin\n" +
                                     "daemon:x:2:2:daemon:/sbin:" +
                                     "/sbin/nologin\n",
                          'gid': 100,
                          'isdir': False,
                          'mode': 0o700,
                          'uid': 100})
        shadow = vfs.handle.files["/etc/shadow"]

        # if the encrypted password is only 13 characters long, then
        # nova.virt.disk.api:_set_password fell back to DES.
        if len(shadow['content']) == 91:
            self.assertEqual(shadow,
                             {'content': "root:12tir.zIbWQ3c" +
                                         ":14917:0:99999:7:::\n" +
                                         "bin:*:14495:0:99999:7:::\n" +
                                         "daemon:*:14495:0:99999:7:::\n",
                              'gid': 100,
                              'isdir': False,
                              'mode': 0o700,
                              'uid': 100})
        else:
            self.assertEqual(shadow,
                             {'content': "root:$1$12345678$a4ge4d5iJ5vw" +
                                         "vbFS88TEN0:14917:0:99999:7:::\n" +
                                         "bin:*:14495:0:99999:7:::\n" +
                                         "daemon:*:14495:0:99999:7:::\n",
                              'gid': 100,
                              'isdir': False,
                              'mode': 0o700,
                              'uid': 100})
        vfs.teardown()

    def test_inject_files_into_fs(self):
        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        diskapi._inject_files_into_fs([("/path/to/not/exists/file",
                                        "inject-file-contents")],
                                      vfs)

        self.assertIn("/path/to/not/exists", vfs.handle.files)
        shadow_dir = vfs.handle.files["/path/to/not/exists"]
        self.assertEqual(shadow_dir,
                         {"isdir": True,
                          "gid": 0,
                          "uid": 0,
                          "mode": 0o744})

        shadow_file = vfs.handle.files["/path/to/not/exists/file"]
        self.assertEqual(shadow_file,
                         {"isdir": False,
                          "content": "inject-file-contents",
                          "gid": 100,
                          "uid": 100,
                          "mode": 0o700})
        vfs.teardown()

    def test_inject_files_into_fs_dir_exists(self):
        vfs = vfsguestfs.VFSGuestFS(self.file)
        vfs.setup()

        called = {'make_path': False}

        def fake_has_file(*args, **kwargs):
            return True

        def fake_make_path(*args, **kwargs):
            called['make_path'] = True

        self.stub_out('nova.virt.disk.vfs.guestfs.VFSGuestFS.has_file',
                      fake_has_file)
        self.stub_out('nova.virt.disk.vfs.guestfs.VFSGuestFS.make_path',
                      fake_make_path)

        # test for already exists dir
        diskapi._inject_files_into_fs([("/path/to/exists/file",
                                        "inject-file-contents")],
                                      vfs)

        self.assertIn("/path/to/exists/file", vfs.handle.files)
        self.assertFalse(called['make_path'])

        # test for root dir
        diskapi._inject_files_into_fs([("/inject-file",
                                        "inject-file-contents")],
                                      vfs)

        self.assertIn("/inject-file", vfs.handle.files)
        self.assertFalse(called['make_path'])

        # test for null dir
        vfs.handle.files.pop("/inject-file")
        diskapi._inject_files_into_fs([("inject-file",
                                        "inject-file-contents")],
                                      vfs)

        self.assertIn("/inject-file", vfs.handle.files)
        self.assertFalse(called['make_path'])

        vfs.teardown()
