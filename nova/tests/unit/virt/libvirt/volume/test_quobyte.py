# Copyright (c) 2015 Quobyte Inc.
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
"""Unit tests for the Quobyte volume driver module."""

import os
import traceback

import ddt
import mock
from oslo_concurrency import processutils
from oslo_utils import fileutils
import psutil
import six

from nova import exception as nova_exception
from nova import test
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import quobyte


@ddt.ddt
@mock.patch.object(quobyte, '_is_systemd', None)
class QuobyteTestCase(test.NoDBTestCase):
    """Tests the nova.virt.libvirt.volume.quobyte module utilities."""

    TEST_MNT_POINT = mock.sentinel.TEST_MNT_POINT

    def assertRaisesAndMessageMatches(
            self, excClass, msg, callableObj, *args, **kwargs):
        """Ensure that the specified exception was raised. """

        caught = False
        try:
            callableObj(*args, **kwargs)
        except Exception as exc:
            caught = True
            self.assertIsInstance(exc, excClass,
                                  'Wrong exception caught: %s Stacktrace: %s' %
                                  (exc, traceback.format_exc()))
            self.assertIn(msg, six.text_type(exc))

        if not caught:
            self.fail('Expected raised exception but nothing caught.')

    def get_mock_partitions(self):
        mypart = mock.Mock()
        mypart.device = "quobyte@"
        mypart.mountpoint = self.TEST_MNT_POINT
        return [mypart]

    @ddt.data(u"starting", u"running", u"degraded")
    @mock.patch.object(psutil.Process, "name", return_value="systemd")
    @mock.patch.object(processutils, "execute")
    def test_quobyte_is_systemd_ok(self, value, mock_execute, mock_proc):
        mock_execute.return_value = [value, "fake stderr"]

        self.assertTrue(quobyte.is_systemd())
        mock_execute.assert_called_once_with("systemctl",
                                             "is-system-running",
                                             check_exit_code=[0, 1])
        mock_proc.assert_called_once()
        self.assertTrue(quobyte.is_systemd())

    @mock.patch.object(psutil.Process, "name", return_value="NOT_systemd")
    @mock.patch.object(os.path, "exists", return_value=False)
    def test_quobyte_is_systemd_not(self, mock_exists, mock_proc):
        self.assertFalse(quobyte.is_systemd())
        mock_exists.assert_called_once_with(quobyte.SYSTEMCTL_CHECK_PATH)
        mock_proc.assert_called_once_with()
        self.assertFalse(quobyte.is_systemd())

    @mock.patch.object(psutil.Process, "name", return_value="NOT_systemd")
    @mock.patch.object(processutils, "execute")
    @mock.patch.object(os.path, "exists", return_value=True)
    def test_quobyte_is_systemd_invalid_state(self, mock_exists, mock_execute,
                                              mock_proc):
        mock_execute.return_value = ["FAKE_UNACCEPTABLE_STATE", "fake stderr"]

        self.assertFalse(quobyte.is_systemd())

        mock_exists.assert_called_once_with(quobyte.SYSTEMCTL_CHECK_PATH)
        mock_execute.assert_called_once_with("systemctl",
                                             "is-system-running",
                                             check_exit_code=[0, 1])
        mock_proc.assert_called_once_with()
        self.assertFalse(quobyte.is_systemd())

    @ddt.data(None, '/some/arbitrary/path')
    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch('nova.privsep.libvirt.unprivileged_qb_mount')
    def test_quobyte_mount_volume_not_systemd(self, cfg_file, mock_mount,
                                              mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte._is_systemd = False
        quobyte.mount_volume(quobyte_volume, export_mnt_base, cfg_file)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        expected_commands = [mock.call(quobyte_volume, export_mnt_base,
                                       cfg_file=cfg_file)]
        mock_mount.assert_has_calls(expected_commands)

    @ddt.data(None, '/some/arbitrary/path')
    @mock.patch('nova.privsep.libvirt.systemd_run_qb_mount')
    @mock.patch.object(fileutils, "ensure_tree")
    def test_quobyte_mount_volume_systemd(self, cfg_file, mock_ensure_tree,
                                          mock_privsep_sysdr):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        quobyte._is_systemd = True

        quobyte.mount_volume(quobyte_volume, export_mnt_base, cfg_file)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        mock_privsep_sysdr.assert_called_once_with(quobyte_volume,
                                                   export_mnt_base,
                                                   cfg_file=cfg_file)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch('nova.privsep.libvirt.unprivileged_qb_mount',
                side_effect=processutils.ProcessExecutionError)
    def test_quobyte_mount_volume_fails(self, mock_mount, mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        quobyte._is_systemd = False
        self.assertRaises(processutils.ProcessExecutionError,
                          quobyte.mount_volume,
                          quobyte_volume,
                          export_mnt_base)
        mock_ensure_tree.assert_called_once_with(export_mnt_base)

    @mock.patch('nova.privsep.libvirt.unprivileged_umount')
    def test_quobyte_umount_volume_non_sysd(self, mock_lv_umount):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte._is_systemd = False
        quobyte.umount_volume(export_mnt_base)

        mock_lv_umount.assert_called_once_with(export_mnt_base)

    @mock.patch('nova.privsep.libvirt.umount')
    def test_quobyte_umount_volume_sysd(self, mock_lv_umount):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        quobyte._is_systemd = True

        quobyte.umount_volume(export_mnt_base)

        mock_lv_umount.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte.LOG, "error")
    @mock.patch('nova.privsep.libvirt.umount')
    def test_quobyte_umount_volume_warns(self, mock_execute, mock_debug):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        quobyte._is_systemd = True

        def exec_side_effect(*cmd, **kwargs):
            exerror = processutils.ProcessExecutionError(
                                       "Device or resource busy")
            raise exerror
        mock_execute.side_effect = exec_side_effect

        quobyte.umount_volume(export_mnt_base)

        (mock_debug.
         assert_called_once_with("The Quobyte volume at %s is still in use.",
                                 export_mnt_base))

    @mock.patch.object(quobyte.LOG, "exception")
    @mock.patch('nova.privsep.libvirt.umount',
                side_effect=processutils.ProcessExecutionError)
    def test_quobyte_umount_volume_fails(self, mock_unmount, mock_exception):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        quobyte._is_systemd = True

        quobyte.umount_volume(export_mnt_base)

        mock_unmount.assert_called_once_with(export_mnt_base)
        (mock_exception.
         assert_called_once_with("Couldn't unmount "
                                 "the Quobyte Volume at %s",
                                 export_mnt_base))

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_all_good_prefix_val(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        drv = quobyte

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                stat_result = mock.Mock()
                stat_result.st_size = 0
                return stat_result
            return os.stat(args)
        stat_mock.side_effect = statMockCall

        drv.validate_volume(self.TEST_MNT_POINT)

        stat_mock.assert_called_once_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_all_good_fs_type(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        part_mock.return_value[0].device = "not_quobyte"
        part_mock.return_value[0].fstype = "fuse.quobyte"
        drv = quobyte

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                stat_result = mock.Mock()
                stat_result.st_size = 0
                return stat_result
            return os.stat(args)
        stat_mock.side_effect = statMockCall

        drv.validate_volume(self.TEST_MNT_POINT)

        stat_mock.assert_called_once_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_mount_not_working(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        drv = quobyte

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                raise nova_exception.InvalidVolume()
        stat_mock.side_effect = [os.stat, statMockCall]

        self.assertRaises(
            excClass=nova_exception.InvalidVolume,
            callableObj=drv.validate_volume,
            mount_path=self.TEST_MNT_POINT)
        stat_mock.assert_called_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_no_mtab_entry(self, part_mock):
        part_mock.return_value = []  # no quobyte@ devices
        msg = ("No matching Quobyte mount entry for %(mpt)s"
               " could be found for validation in partition list."
               % {'mpt': self.TEST_MNT_POINT})

        self.assertRaisesAndMessageMatches(
            nova_exception.InvalidVolume,
            msg,
            quobyte.validate_volume,
            self.TEST_MNT_POINT)

    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_wrong_mount_type(self, part_mock):
        mypart = mock.Mock()
        mypart.device = "not-quobyte"
        mypart.mountpoint = self.TEST_MNT_POINT
        part_mock.return_value = [mypart]
        msg = ("The mount %(mpt)s is not a valid"
               " Quobyte volume according to partition list."
               % {'mpt': self.TEST_MNT_POINT})

        self.assertRaisesAndMessageMatches(
            nova_exception.InvalidVolume,
            msg,
            quobyte.validate_volume,
            self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(os, "stat")
    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_stale_mount(self, part_mock, stat_mock):
        part_mock.return_value = self.get_mock_partitions()

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                stat_result = mock.Mock()
                stat_result.st_size = 1
                return stat_result
            return os.stat(args)
        stat_mock.side_effect = statMockCall

        # As this uses a dir size >0, it raises an exception
        self.assertRaises(
            nova_exception.InvalidVolume,
            quobyte.validate_volume,
            self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)


class LibvirtQuobyteVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):
    """Tests the LibvirtQuobyteVolumeDriver class."""

    @mock.patch.object(quobyte, 'umount_volume')
    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=False)
    def test_libvirt_quobyte_driver_mount(self,
                                          mock_is_mounted,
                                          mock_mount_volume,
                                          mock_validate_volume,
                                          mock_umount_volume
                                          ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        mock_validate_volume.side_effect = [nova_exception.StaleVolumeMount(
            "This shall fail."), True, True]

        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self._assertFileTypeEquals(tree, file_path)

        mock_mount_volume.assert_called_once_with(quobyte_volume,
                                                  export_mnt_base,
                                                  mock.ANY)
        mock_validate_volume.assert_called_with(export_mnt_base)
        mock_umount_volume.assert_called_once_with(
            libvirt_driver._get_mount_path(connection_info))

    @mock.patch.object(quobyte, 'validate_volume', return_value=True)
    @mock.patch.object(quobyte, 'umount_volume')
    def test_libvirt_quobyte_driver_umount(self, mock_umount_volume,
                                           mock_validate_volume):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)

        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        mock_validate_volume.assert_has_calls([mock.call(export_mnt_base),
                                               mock.call(export_mnt_base),
                                               mock.call(export_mnt_base)])
        mock_umount_volume.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'umount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=True)
    def test_libvirt_quobyte_driver_already_mounted(self,
                                                    mock_is_mounted,
                                                    mock_umount_volume,
                                                    mock_validate_volume
                                                    ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        mock_umount_volume.assert_called_once_with(export_mnt_base)
        mock_validate_volume.assert_has_calls([mock.call(export_mnt_base),
                                               mock.call(export_mnt_base)])

    @mock.patch.object(quobyte, 'umount_volume')
    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    def test_libvirt_quobyte_driver_qcow2(self, mock_mount_volume,
                                          mock_validate_volume, mock_umount):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')
        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        name = 'volume-00001'
        image_format = 'qcow2'
        quobyte_volume = '192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': name,
                                    'format': image_format}}

        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        mock_validate_volume.side_effect = [nova_exception.StaleVolumeMount(
            "This shall fail."), True, True]

        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('file', tree.get('type'))
        self.assertEqual('qcow2', tree.find('./driver').get('type'))

        (mock_mount_volume.
         assert_called_once_with('192.168.1.1/volume-00001',
                                 export_mnt_base,
                                 mock.ANY))
        mock_validate_volume.assert_called_with(export_mnt_base)

        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)
        mock_umount.assert_has_calls([mock.call(export_mnt_base),
                                      mock.call(export_mnt_base)])

    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=True)
    def test_libvirt_quobyte_driver_mount_non_quobyte_volume(self,
            mock_is_mounted):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        def exe_side_effect(*cmd, **kwargs):
            if cmd == mock.ANY:
                raise nova_exception.NovaException()

        with mock.patch.object(quobyte,
                               'validate_volume') as mock_execute:
            mock_execute.side_effect = exe_side_effect
            self.assertRaises(nova_exception.NovaException,
                              libvirt_driver.connect_volume,
                              connection_info,
                              mock.sentinel.instance)

    def test_libvirt_quobyte_driver_normalize_export_with_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        self.assertEqual("192.168.1.1/volume-00001",
                         libvirt_driver._normalize_export(export_string))

    def test_libvirt_quobyte_driver_normalize_export_without_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_host)
        export_string = '192.168.1.1/volume-00001'
        self.assertEqual("192.168.1.1/volume-00001",
                         libvirt_driver._normalize_export(export_string))
