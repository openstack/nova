# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

import sys

from nova import exception
from nova import test

from nova.tests import fakeguestfs
from nova.virt.disk.vfs import guestfs as vfsimpl


class VirtDiskVFSGuestFSTest(test.TestCase):

    def setUp(self):
        super(VirtDiskVFSGuestFSTest, self).setUp()
        sys.modules['guestfs'] = fakeguestfs
        vfsimpl.guestfs = fakeguestfs

    def test_appliance_setup_inspect(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=-1)
        vfs.setup()

        self.assertEqual(vfs.handle.running, True)
        self.assertEqual(len(vfs.handle.mounts), 3)
        self.assertEqual(vfs.handle.mounts[0][1],
                         "/dev/mapper/guestvgf-lv_root")
        self.assertEqual(vfs.handle.mounts[1][1], "/dev/vda1")
        self.assertEqual(vfs.handle.mounts[2][1],
                         "/dev/mapper/guestvgf-lv_home")
        self.assertEqual(vfs.handle.mounts[0][2], "/")
        self.assertEqual(vfs.handle.mounts[1][2], "/boot")
        self.assertEqual(vfs.handle.mounts[2][2], "/home")

        handle = vfs.handle
        vfs.teardown()

        self.assertEqual(vfs.handle, None)
        self.assertEqual(handle.running, False)
        self.assertEqual(handle.closed, True)
        self.assertEqual(len(handle.mounts), 0)

    def test_appliance_setup_inspect_no_root_raises(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=-1)
        # call setup to init the handle so we can stub it
        vfs.setup()

        def fake_inspect_os():
            return []

        self.stubs.Set(vfs.handle, 'inspect_os', fake_inspect_os)
        self.assertRaises(exception.NovaException, vfs.setup_os_inspect)

    def test_appliance_setup_inspect_multi_boots_raises(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=-1)
        # call setup to init the handle so we can stub it
        vfs.setup()

        def fake_inspect_os():
            return ['fake1', 'fake2']

        self.stubs.Set(vfs.handle, 'inspect_os', fake_inspect_os)
        self.assertRaises(exception.NovaException, vfs.setup_os_inspect)

    def test_appliance_setup_static_nopart(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=None)
        vfs.setup()

        self.assertEqual(vfs.handle.running, True)
        self.assertEqual(len(vfs.handle.mounts), 1)
        self.assertEqual(vfs.handle.mounts[0][1], "/dev/sda")
        self.assertEqual(vfs.handle.mounts[0][2], "/")

        handle = vfs.handle
        vfs.teardown()

        self.assertEqual(vfs.handle, None)
        self.assertEqual(handle.running, False)
        self.assertEqual(handle.closed, True)
        self.assertEqual(len(handle.mounts), 0)

    def test_appliance_setup_static_part(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=2)
        vfs.setup()

        self.assertEqual(vfs.handle.running, True)
        self.assertEqual(len(vfs.handle.mounts), 1)
        self.assertEqual(vfs.handle.mounts[0][1], "/dev/sda2")
        self.assertEqual(vfs.handle.mounts[0][2], "/")

        handle = vfs.handle
        vfs.teardown()

        self.assertEqual(vfs.handle, None)
        self.assertEqual(handle.running, False)
        self.assertEqual(handle.closed, True)
        self.assertEqual(len(handle.mounts), 0)

    def test_makepath(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.make_path("/some/dir")
        vfs.make_path("/other/dir")

        self.assertTrue("/some/dir" in vfs.handle.files)
        self.assertTrue("/other/dir" in vfs.handle.files)
        self.assertTrue(vfs.handle.files["/some/dir"]["isdir"])
        self.assertTrue(vfs.handle.files["/other/dir"]["isdir"])

        vfs.teardown()

    def test_append_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.append_file("/some/file", " Goodbye")

        self.assertTrue("/some/file" in vfs.handle.files)
        self.assertEqual(vfs.handle.files["/some/file"]["content"],
                         "Hello World Goodbye")

        vfs.teardown()

    def test_replace_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.replace_file("/some/file", "Goodbye")

        self.assertTrue("/some/file" in vfs.handle.files)
        self.assertEqual(vfs.handle.files["/some/file"]["content"],
                         "Goodbye")

        vfs.teardown()

    def test_read_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertEqual(vfs.read_file("/some/file"), "Hello World")

        vfs.teardown()

    def test_has_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertTrue(vfs.has_file("/some/file"))
        self.assertFalse(vfs.has_file("/other/file"))

        vfs.teardown()

    def test_set_permissions(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertEquals(vfs.handle.files["/some/file"]["mode"], 0o700)

        vfs.set_permissions("/some/file", 0o7777)
        self.assertEquals(vfs.handle.files["/some/file"]["mode"], 0o7777)

        vfs.teardown()

    def test_set_ownership(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertEquals(vfs.handle.files["/some/file"]["uid"], 100)
        self.assertEquals(vfs.handle.files["/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", "fred", None)
        self.assertEquals(vfs.handle.files["/some/file"]["uid"], 105)
        self.assertEquals(vfs.handle.files["/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", None, "users")
        self.assertEquals(vfs.handle.files["/some/file"]["uid"], 105)
        self.assertEquals(vfs.handle.files["/some/file"]["gid"], 500)

        vfs.set_ownership("/some/file", "joe", "admins")
        self.assertEquals(vfs.handle.files["/some/file"]["uid"], 110)
        self.assertEquals(vfs.handle.files["/some/file"]["gid"], 600)

        vfs.teardown()
