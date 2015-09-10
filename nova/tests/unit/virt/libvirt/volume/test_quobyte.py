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

import mock
import os

from oslo_concurrency import processutils
from oslo_utils import fileutils

from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import quobyte


class QuobyteTestCase(test.NoDBTestCase):
    """Tests the nova.virt.libvirt.volume.quobyte module utilities."""

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute")
    def test_quobyte_mount_volume(self, mock_execute, mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.mount_volume(quobyte_volume, export_mnt_base)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        expected_commands = [mock.call('mount.quobyte',
                                       quobyte_volume,
                                       export_mnt_base,
                                       check_exit_code=[0, 4])
                             ]
        mock_execute.assert_has_calls(expected_commands)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute")
    def test_quobyte_mount_volume_with_config(self,
                                              mock_execute,
                                              mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        config_file_dummy = "/etc/quobyte/dummy.conf"

        quobyte.mount_volume(quobyte_volume,
                             export_mnt_base,
                             config_file_dummy)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        expected_commands = [mock.call('mount.quobyte',
                                       quobyte_volume,
                                       export_mnt_base,
                                       '-c',
                                       config_file_dummy,
                                       check_exit_code=[0, 4])
                             ]
        mock_execute.assert_has_calls(expected_commands)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_mount_volume_fails(self, mock_execute, mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(processutils.ProcessExecutionError,
                          quobyte.mount_volume,
                          quobyte_volume,
                          export_mnt_base)

    @mock.patch.object(utils, "execute")
    def test_quobyte_umount_volume(self, mock_execute):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.umount_volume(export_mnt_base)

        mock_execute.assert_called_once_with('umount.quobyte',
                                             export_mnt_base)

    @mock.patch.object(quobyte.LOG, "error")
    @mock.patch.object(utils, "execute")
    def test_quobyte_umount_volume_warns(self,
                                         mock_execute,
                                         mock_debug):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

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
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.ProcessExecutionError))
    def test_quobyte_umount_volume_fails(self,
                                         mock_execute,
                                         mock_exception):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.umount_volume(export_mnt_base)

        (mock_exception.
         assert_called_once_with("Couldn't unmount "
                                 "the Quobyte Volume at %s",
                                 export_mnt_base))

    @mock.patch.object(os, "access", return_value=True)
    @mock.patch.object(utils, "execute")
    def test_quobyte_is_valid_volume(self, mock_execute, mock_access):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.validate_volume(export_mnt_base)

        mock_execute.assert_called_once_with('getfattr',
                                             '-n',
                                             'quobyte.info',
                                             export_mnt_base)

    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_is_valid_volume_vol_not_valid_volume(self, mock_execute):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(exception.NovaException,
                          quobyte.validate_volume,
                          export_mnt_base)

    @mock.patch.object(os, "access", return_value=False)
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_is_valid_volume_vol_no_valid_access(self,
                                                         mock_execute,
                                                         mock_access):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(exception.NovaException,
                          quobyte.validate_volume,
                          export_mnt_base)


class LibvirtQuobyteVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):
    """Tests the LibvirtQuobyteVolumeDriver class."""

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=False)
    def test_libvirt_quobyte_driver_mount(self,
                                          mock_is_mounted,
                                          mock_mount_volume,
                                          mock_validate_volume
                                          ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self._assertFileTypeEquals(tree, file_path)

        mock_mount_volume.assert_called_once_with(quobyte_volume,
                                                  export_mnt_base,
                                                  mock.ANY)
        mock_validate_volume.assert_called_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'umount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=True)
    def test_libvirt_quobyte_driver_umount(self, mock_is_mounted,
                                           mock_umount_volume,
                                           mock_validate_volume):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)

        libvirt_driver.disconnect_volume(connection_info, "vde")

        mock_validate_volume.assert_called_once_with(export_mnt_base)
        mock_umount_volume.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'umount_volume')
    def test_libvirt_quobyte_driver_already_mounted(self,
                                                    mock_umount_volume,
                                                    mock_validate_volume
                                                    ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base,
             '--source', "quobyte@" + quobyte_volume),
            ('findmnt', '--target', export_mnt_base,
             '--source', "quobyte@" + quobyte_volume),
            ]
        self.assertEqual(expected_commands, self.executes)

        mock_umount_volume.assert_called_once_with(export_mnt_base)
        mock_validate_volume.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=False)
    def test_libvirt_quobyte_driver_qcow2(self, mock_is_mounted,
                                          mock_mount_volume,
                                          mock_validate_volume
                                          ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')
        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        name = 'volume-00001'
        image_format = 'qcow2'
        quobyte_volume = '192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': name,
                                    'format': image_format}}

        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        libvirt_driver.connect_volume(connection_info, self.disk_info)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('file', tree.get('type'))
        self.assertEqual('qcow2', tree.find('./driver').get('type'))

        (mock_mount_volume.
         assert_called_once_with('192.168.1.1/volume-00001',
                                 export_mnt_base,
                                 mock.ANY))
        mock_validate_volume.assert_called_with(export_mnt_base)

        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_quobyte_driver_mount_non_quobyte_volume(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        def exe_side_effect(*cmd, **kwargs):
            if cmd == mock.ANY:
                raise exception.NovaException()

        with mock.patch.object(quobyte,
                               'validate_volume') as mock_execute:
            mock_execute.side_effect = exe_side_effect
            self.assertRaises(exception.NovaException,
                              libvirt_driver.connect_volume,
                              connection_info,
                              self.disk_info)

    def test_libvirt_quobyte_driver_normalize_export_with_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        self.assertEqual("192.168.1.1/volume-00001",
                         libvirt_driver._normalize_export(export_string))

    def test_libvirt_quobyte_driver_normalize_export_without_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = quobyte.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = '192.168.1.1/volume-00001'
        self.assertEqual("192.168.1.1/volume-00001",
                         libvirt_driver._normalize_export(export_string))
