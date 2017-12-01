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
from nova.virt.image import model as imgmodel


class VirtDiskVFSGuestFSTest(test.NoDBTestCase):
    def setUp(self):
        super(VirtDiskVFSGuestFSTest, self).setUp()
        self.useFixture(
                fixtures.MonkeyPatch('nova.virt.disk.vfs.guestfs.guestfs',
                                     fakeguestfs))

        self.qcowfile = imgmodel.LocalFileImage("/dummy.qcow2",
                                                imgmodel.FORMAT_QCOW2)
        self.rawfile = imgmodel.LocalFileImage("/dummy.img",
                                               imgmodel.FORMAT_RAW)
        self.lvmfile = imgmodel.LocalBlockImage("/dev/volgroup/myvol")
        self.rbdfile = imgmodel.RBDImage("myvol", "mypool",
                                         "cthulu",
                                         "arrrrrgh",
                                         ["server1:123", "server2:123"])

    def _do_test_appliance_setup_inspect(self, image, drives, forcetcg):
        if forcetcg:
            vfsimpl.force_tcg()
        else:
            vfsimpl.force_tcg(False)

        vfs = vfsimpl.VFSGuestFS(
            image,
            partition=-1)
        vfs.setup()

        if forcetcg:
            self.assertEqual(["force_tcg"], vfs.handle.backend_settings)
            vfsimpl.force_tcg(False)
        else:
            self.assertIsNone(vfs.handle.backend_settings)

        self.assertTrue(vfs.handle.running)
        self.assertEqual(drives,
                         vfs.handle.drives)
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
        drives = [("/dummy.qcow2", {"format": "qcow2"})]
        self._do_test_appliance_setup_inspect(self.qcowfile, drives, False)

    def test_appliance_setup_inspect_tcg(self):
        drives = [("/dummy.qcow2", {"format": "qcow2"})]
        self._do_test_appliance_setup_inspect(self.qcowfile, drives, True)

    def test_appliance_setup_inspect_raw(self):
        drives = [("/dummy.img", {"format": "raw"})]
        self._do_test_appliance_setup_inspect(self.rawfile, drives, True)

    def test_appliance_setup_inspect_lvm(self):
        drives = [("/dev/volgroup/myvol", {"format": "raw"})]
        self._do_test_appliance_setup_inspect(self.lvmfile, drives, True)

    def test_appliance_setup_inspect_rbd(self):
        drives = [("mypool/myvol", {"format": "raw",
                                    "protocol": "rbd",
                                    "username": "cthulu",
                                    "secret": "arrrrrgh",
                                    "server": ["server1:123",
                                               "server2:123"]})]
        self._do_test_appliance_setup_inspect(self.rbdfile, drives, True)

    def test_appliance_setup_inspect_no_root_raises(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile,
                                 partition=-1)
        # call setup to init the handle so we can stub it
        vfs.setup()

        self.assertIsNone(vfs.handle.backend_settings)
        with mock.patch.object(
            vfs.handle, 'inspect_os', return_value=[]) as mock_inspect_os:
            self.assertRaises(exception.NovaException, vfs.setup_os_inspect)
            mock_inspect_os.assert_called_once_with()

    def test_appliance_setup_inspect_multi_boots_raises(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile,
                                 partition=-1)
        # call setup to init the handle so we can stub it
        vfs.setup()

        self.assertIsNone(vfs.handle.backend_settings)

        with mock.patch.object(
            vfs.handle, 'inspect_os',
            return_value=['fake1', 'fake2']) as mock_inspect_os:
            self.assertRaises(exception.NovaException, vfs.setup_os_inspect)
            mock_inspect_os.assert_called_once_with()

    def test_appliance_setup_static_nopart(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile,
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
        vfs = vfsimpl.VFSGuestFS(self.qcowfile,
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
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        vfs.make_path("/some/dir")
        vfs.make_path("/other/dir")

        self.assertIn("/some/dir", vfs.handle.files)
        self.assertIn("/other/dir", vfs.handle.files)
        self.assertTrue(vfs.handle.files["/some/dir"]["isdir"])
        self.assertTrue(vfs.handle.files["/other/dir"]["isdir"])

        vfs.teardown()

    def test_append_file(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        vfs.append_file("/some/file", " Goodbye")

        self.assertIn("/some/file", vfs.handle.files)
        self.assertEqual("Hello World Goodbye",
                         vfs.handle.files["/some/file"]["content"])

        vfs.teardown()

    def test_replace_file(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        vfs.replace_file("/some/file", "Goodbye")

        self.assertIn("/some/file", vfs.handle.files)
        self.assertEqual("Goodbye",
                         vfs.handle.files["/some/file"]["content"])

        vfs.teardown()

    def test_read_file(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertEqual("Hello World", vfs.read_file("/some/file"))

        vfs.teardown()

    def test_has_file(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertTrue(vfs.has_file("/some/file"))
        self.assertFalse(vfs.has_file("/other/file"))

        vfs.teardown()

    def test_set_permissions(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        vfs.read_file("/some/file")

        self.assertEqual(0o700, vfs.handle.files["/some/file"]["mode"])

        vfs.set_permissions("/some/file", 0o7777)
        self.assertEqual(0o7777, vfs.handle.files["/some/file"]["mode"])

        vfs.teardown()

    def test_set_ownership(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
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

    def test_set_ownership_not_supported(self):
        # NOTE(andreaf) Setting ownership relies on /etc/passwd and/or
        # /etc/group being available in the image, which is not always the
        # case - e.g. CirrOS image before boot.
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.stub_out('nova.tests.unit.virt.disk.vfs.fakeguestfs.GuestFS.'
                      'CAN_SET_OWNERSHIP', False)

        self.assertRaises(exception.NovaException, vfs.set_ownership,
                          "/some/file", "fred", None)
        self.assertRaises(exception.NovaException, vfs.set_ownership,
                          "/some/file", None, "users")

    def test_close_on_error(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertFalse(vfs.handle.kwargs['close_on_exit'])
        vfs.teardown()
        self.stub_out('nova.tests.unit.virt.disk.vfs.fakeguestfs.GuestFS.'
                      'SUPPORT_CLOSE_ON_EXIT', False)
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertNotIn('close_on_exit', vfs.handle.kwargs)
        vfs.teardown()

    def test_python_return_dict(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertFalse(vfs.handle.kwargs['python_return_dict'])
        vfs.teardown()
        self.stub_out('nova.tests.unit.virt.disk.vfs.fakeguestfs.GuestFS.'
                      'SUPPORT_RETURN_DICT', False)
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertNotIn('python_return_dict', vfs.handle.kwargs)
        vfs.teardown()

    def test_setup_debug_disable(self):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertFalse(vfs.handle.trace_enabled)
        self.assertFalse(vfs.handle.verbose_enabled)
        self.assertIsNone(vfs.handle.event_callback)

    def test_setup_debug_enabled(self):
        self.flags(debug=True, group='guestfs')
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertTrue(vfs.handle.trace_enabled)
        self.assertTrue(vfs.handle.verbose_enabled)
        self.assertIsNotNone(vfs.handle.event_callback)

    def test_get_format_fs(self):
        vfs = vfsimpl.VFSGuestFS(self.rawfile)
        vfs.setup()
        self.assertIsNotNone(vfs.handle)
        self.assertEqual('ext3', vfs.get_image_fs())
        vfs.teardown()

    @mock.patch.object(vfsimpl.VFSGuestFS, 'setup_os')
    def test_setup_mount(self, setup_os):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup()
        self.assertTrue(setup_os.called)

    @mock.patch.object(vfsimpl.VFSGuestFS, 'setup_os')
    def test_setup_mount_false(self, setup_os):
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        vfs.setup(mount=False)
        self.assertFalse(setup_os.called)

    @mock.patch('os.access')
    @mock.patch('os.uname', return_value=('Linux', '', 'kernel_name'))
    def test_appliance_setup_inspect_capabilties_fail_with_ubuntu(self,
                                                                  mock_uname,
                                                                  mock_access):
        # In ubuntu os will default host kernel as 600 permission
        m = mock.MagicMock()
        m.launch.side_effect = Exception
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        mock_access.return_value = False
        self.flags(debug=False, group='guestfs')
        with mock.patch('eventlet.tpool.Proxy', return_value=m) as tpool_mock:
            self.assertRaises(exception.LibguestfsCannotReadKernel,
                                    vfs.inspect_capabilities)
            m.add_drive.assert_called_once_with('/dev/null')
            m.launch.assert_called_once_with()
            mock_access.assert_called_once_with('/boot/vmlinuz-kernel_name',
                                                mock.ANY)
            mock_uname.assert_called_once_with()
            self.assertEqual(1, tpool_mock.call_count)

    def test_appliance_setup_inspect_capabilties_debug_mode(self):
        """Asserts that we do not use an eventlet thread pool when guestfs
        debug logging is enabled.
        """
        # We can't actually mock guestfs.GuestFS because it's an optional
        # native package import. All we really care about here is that
        # eventlet isn't used.
        self.flags(debug=True, group='guestfs')
        vfs = vfsimpl.VFSGuestFS(self.qcowfile)
        with mock.patch('eventlet.tpool.Proxy',
                        new_callable=mock.NonCallableMock):
            vfs.inspect_capabilities()
