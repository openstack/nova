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

import os

import mock

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import smbfs


class LibvirtSMBFSVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    """Tests the libvirt SMBFS volume driver."""

    def setUp(self):
        super(LibvirtSMBFSVolumeDriverTestCase, self).setUp()
        self.mnt_base = '/mnt'
        self.flags(smbfs_mount_point_base=self.mnt_base, group='libvirt')

    @mock.patch.object(libvirt_utils, 'is_mounted')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    def test_libvirt_smbfs_driver(self, mock_umount, mock_mount,
                                  mock_ensure_tree, mock_is_mounted):
        mock_is_mounted.return_value = False

        libvirt_driver = smbfs.LibvirtSMBFSVolumeDriver(self.fake_host)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(self.mnt_base,
                                       utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': None}}
        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        mock_ensure_tree.assert_has_calls([mock.call(export_mnt_base)])
        mock_mount.assert_has_calls(
            [mock.call('cifs', export_string, export_mnt_base,
                       ['-o', 'username=guest'])])
        mock_umount.assert_has_calls([mock.call(export_mnt_base)])

    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=True)
    @mock.patch('nova.privsep.fs.umount')
    def test_libvirt_smbfs_driver_already_mounted(self, mock_umount,
                                                  mock_is_mounted):
        libvirt_driver = smbfs.LibvirtSMBFSVolumeDriver(self.fake_host)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(self.mnt_base,
                                       utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        mock_umount.assert_has_calls([mock.call(export_mnt_base)])

    def test_libvirt_smbfs_driver_get_config(self):
        libvirt_driver = smbfs.LibvirtSMBFSVolumeDriver(self.fake_host)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(self.mnt_base,
                                       utils.get_hash_str(export_string))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)

    @mock.patch.object(libvirt_utils, 'is_mounted')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    def test_libvirt_smbfs_driver_with_opts(self, mock_umount, mock_mount,
                                            mock_ensure_tree, mock_is_mounted):
        mock_is_mounted.return_value = False

        libvirt_driver = smbfs.LibvirtSMBFSVolumeDriver(self.fake_host)
        export_string = '//192.168.1.1/volumes'
        options = '-o user=guest,uid=107,gid=105'
        export_mnt_base = os.path.join(self.mnt_base,
            utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}

        libvirt_driver.connect_volume(connection_info, mock.sentinel.instance)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        mock_ensure_tree.assert_has_calls([mock.call(export_mnt_base)])
        mock_mount.assert_has_calls(
            [mock.call('cifs', export_string, export_mnt_base,
                       ['-o', 'user=guest,uid=107,gid=105'])])
        mock_umount.assert_has_calls([mock.call(export_mnt_base)])
