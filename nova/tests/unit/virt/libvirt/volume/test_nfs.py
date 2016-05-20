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
from oslo_concurrency import processutils

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import nfs


class LibvirtNFSVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    """Tests the libvirt NFS volume driver."""

    def setUp(self):
        super(LibvirtNFSVolumeDriverTestCase, self).setUp()
        self.mnt_base = '/mnt'
        self.flags(nfs_mount_point_base=self.mnt_base, group='libvirt')

    def test_libvirt_nfs_driver(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)

        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(connection_info['data']['device_path'], device_path)
        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', export_string, export_mnt_base),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    @mock.patch.object(nfs.utils, 'execute')
    @mock.patch.object(nfs.LOG, 'debug')
    @mock.patch.object(nfs.LOG, 'exception')
    def test_libvirt_nfs_driver_umount_error(self, mock_LOG_exception,
                                        mock_LOG_debug, mock_utils_exe):
        export_string = '192.168.1.1:/nfs/share1'
        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_conn)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: device is busy.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_debug.called)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: target is busy.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_debug.called)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: not mounted.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_debug.called)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: Other error.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_exception.called)

    def test_libvirt_nfs_driver_get_config(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_conn)
        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                                       utils.get_hash_str(export_string))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        self.assertEqual('raw', tree.find('./driver').get('type'))
        self.assertEqual('native', tree.find('./driver').get('io'))

    def test_libvirt_nfs_driver_already_mounted(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_conn)

        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base, '--source',
             export_string),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_nfs_driver_with_opts(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)
        export_string = '192.168.1.1:/nfs/share1'
        options = '-o intr,nfsvers=3'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', '-o', 'intr,nfsvers=3',
             export_string, export_mnt_base),
            ('umount', export_mnt_base),
        ]
        self.assertEqual(expected_commands, self.executes)
