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

import fixtures
import mock

from nova import exception
from nova import test
from nova.tests.unit.virt.disk.vfs import fakeguestfs
from nova.virt.disk.vfs import guestfs as vfsimpl


class VirtDiskVFSGuestFSTest(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSGuestFSTest, self).setUp()
        self.useFixture(
                fixtures.MonkeyPatch('nova.virt.disk.vfs.guestfs.guestfs',
                                     fakeguestfs))

    def _do_test_appliance_setup_inspect(self, forcetcg):
        if forcetcg:
            vfsimpl.force_tcg()
        else:
            vfsimpl.force_tcg(False)

        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=-1)
        vfs.setup()

        if forcetcg:
            self.assertEqual("force_tcg", vfs.handle.backend_settings)
            vfsimpl.force_tcg(False)
        else:
            self.assertIsNone(vfs.handle.backend_settings)

        self.assertTrue(vfs.handle.running)
        self.assertEqual(3, len(vfs.handle.mounts))
        self.assertEqual("/dev/mapper/guestvgf-lv_root",
                         vfs.handle.mounts[0][1])
        self.assertEqual("/dev/vda1",
                         vfs.handle.mounts[1][1])
        self.assertEqual("/dev/mapper/guestvgf-lv_home",
                         vfs.handle.mounts[2][1])
        self.assertEqual("/", vfs.handle.mounts[0][2])
        self.assertEqual("/boot", vfs.handle.mounts[1][2])
        self.assertEqual("/home", vfs.handle.mounts[2][2])

        handle = vfs.handle
        vfs.teardown()

        self.assertIsNone(vfs.handle)
        self.assertFalse(handle.running)
        self.assertTrue(handle.closed)
        self.assertEqual(0, len(handle.mounts))

    def test_appliance_setup_inspect_auto(self):
        self._do_test_appliance_setup_inspect(False)

    def test_appliance_setup_inspect_tcg(self):
        self._do_test_appliance_setup_inspect(True)

    def test_appliance_setup_inspect_no_root_raises(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=-1)
        # call setup to init the handle so we can stub it
        vfs.setup()

        self.assertIsNone(vfs.handle.backend_settings)

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

        self.assertIsNone(vfs.handle.backend_settings)

        def fake_inspect_os():
            return ['fake1', 'fake2']

        self.stubs.Set(vfs.handle, 'inspect_os', fake_inspect_os)
        self.assertRaises(exception.NovaException, vfs.setup_os_inspect)

    def test_appliance_setup_static_nopart(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=None)
        vfs.setup()

        self.assertIsNone(vfs.handle.backend_settings)
        self.assertTrue(vfs.handle.running)
        self.assertEqual(1, len(vfs.handle.mounts))
        self.assertEqual("/dev/sda", vfs.handle.mounts[0][1])
        self.assertEqual("/", vfs.handle.mounts[0][2])

        handle = vfs.handle
        vfs.teardown()

        self.assertIsNone(vfs.handle)
        self.assertFalse(handle.running)
        self.assertTrue(handle.closed)
        self.assertEqual(0, len(handle.mounts))

    def test_appliance_setup_static_part(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2",
                                 imgfmt="qcow2",
                                 partition=2)
        vfs.setup()

        self.assertIsNone(vfs.handle.backend_settings)
        self.assertTrue(vfs.handle.running)
        self.assertEqual(1, len(vfs.handle.mounts))
        self.assertEqual("/dev/sda2", vfs.handle.mounts[0][1])
        self.assertEqual("/", vfs.handle.mounts[0][2])

        handle = vfs.handle
        vfs.teardown()

        self.assertIsNone(vfs.handle)
        self.assertFalse(handle.running)
        self.assertTrue(handle.closed)
        self.assertEqual(0, len(handle.mounts))

    def test_makepath(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.make_path("/some/dir")
        vfs.make_path("/other/dir")

        self.assertIn("/some/dir", vfs.handle.files)
        self.assertIn("/other/dir", vfs.handle.files)
        self.assertTrue(vfs.handle.files["/some/dir"]["isdir"])
        self.assertTrue(vfs.handle.files["/other/dir"]["isdir"])

        vfs.teardown()

    def test_append_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.append_file("/some/file", " Goodbye")

        self.assertIn("/some/file", vfs.handle.files)
        self.assertEqual("Hello World Goodbye",
                         vfs.handle.files["/some/file"]["content"])

        vfs.teardown()

    def test_replace_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.replace_file("/some/file", "Goodbye")

        self.assertIn("/some/file", vfs.handle.files)
        self.assertEqual("Goodbye",
                         vfs.handle.files["/some/file"]["content"])

        vfs.teardown()

    def test_read_file(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertEqual("Hello World", vfs.read_file("/some/file"))

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

        self.assertEqual(0o700, vfs.handle.files["/some/file"]["mode"])

        vfs.set_permissions("/some/file", 0o7777)
        self.assertEqual(0o7777, vfs.handle.files["/some/file"]["mode"])

        vfs.teardown()

    def test_set_ownership(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertEqual(100, vfs.handle.files["/some/file"]["uid"])
        self.assertEqual(100, vfs.handle.files["/some/file"]["gid"])

        vfs.set_ownership("/some/file", "fred", None)
        self.assertEqual(105, vfs.handle.files["/some/file"]["uid"])
        self.assertEqual(100, vfs.handle.files["/some/file"]["gid"])

        vfs.set_ownership("/some/file", None, "users")
        self.assertEqual(105, vfs.handle.files["/some/file"]["uid"])
        self.assertEqual(500, vfs.handle.files["/some/file"]["gid"])

        vfs.set_ownership("/some/file", "joe", "admins")
        self.assertEqual(110, vfs.handle.files["/some/file"]["uid"])
        self.assertEqual(600, vfs.handle.files["/some/file"]["gid"])

        vfs.teardown()

    def test_close_on_error(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertFalse(vfs.handle.kwargs['close_on_exit'])
        vfs.teardown()
        self.stubs.Set(fakeguestfs.GuestFS, 'SUPPORT_CLOSE_ON_EXIT', False)
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertNotIn('close_on_exit', vfs.handle.kwargs)
        vfs.teardown()

    def test_python_return_dict(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertFalse(vfs.handle.kwargs['python_return_dict'])
        vfs.teardown()
        self.stubs.Set(fakeguestfs.GuestFS, 'SUPPORT_RETURN_DICT', False)
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertNotIn('python_return_dict', vfs.handle.kwargs)
        vfs.teardown()

    def test_setup_debug_disable(self):
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertFalse(vfs.handle.trace_enabled)
        self.assertFalse(vfs.handle.verbose_enabled)
        self.assertIsNone(vfs.handle.event_callback)

    def test_setup_debug_enabled(self):
        self.flags(debug=True, group='guestfs')
        vfs = vfsimpl.VFSGuestFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.setup()
        self.assertTrue(vfs.handle.trace_enabled)
        self.assertTrue(vfs.handle.verbose_enabled)
        self.assertIsNotNone(vfs.handle.event_callback)

    def test_get_format_fs(self):
        vfs = vfsimpl.VFSGuestFS("dummy.img")
        vfs.setup()
        self.assertIsNotNone(vfs.handle)
        self.assertTrue('ext3', vfs.get_image_fs())
        vfs.teardown()

    @mock.patch.object(vfsimpl.VFSGuestFS, 'setup_os')
    def test_setup_mount(self, setup_os):
        vfs = vfsimpl.VFSGuestFS("img.qcow2", imgfmt='qcow2')
        vfs.setup()
        self.assertTrue(setup_os.called)

    @mock.patch.object(vfsimpl.VFSGuestFS, 'setup_os')
    def test_setup_mount_false(self, setup_os):
        vfs = vfsimpl.VFSGuestFS("img.qcow2", imgfmt='qcow2')
        vfs.setup(mount=False)
        self.assertFalse(setup_os.called)
