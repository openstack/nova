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

import fixtures
import mock

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt.libvirt.volume import mount
from nova.virt.libvirt.volume import nfs


class LibvirtNFSVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    """Tests the libvirt NFS volume driver."""

    def setUp(self):
        super(LibvirtNFSVolumeDriverTestCase, self).setUp()

        m = mount.get_manager()
        m._reset_state()

        self.mnt_base = '/mnt'
        m.host_up(self.fake_host)
        self.flags(nfs_mount_point_base=self.mnt_base, group='libvirt')

        # Caution: this is also faked by the superclass
        orig_execute = utils.execute

        mounted = [False]

        def fake_execute(*cmd, **kwargs):
            orig_execute(*cmd, **kwargs)

            if cmd[0] == 'mount':
                mounted[0] = True

            if cmd[0] == 'umount':
                mounted[0] = False

        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute',
                                             fake_execute))

        # Mock ismount to return the current mount state
        # N.B. This is only valid for tests which mount and unmount a single
        # directory.
        self.useFixture(fixtures.MonkeyPatch('os.path.ismount',
                                         lambda *args, **kwargs: mounted[0]))

    def test_libvirt_nfs_driver(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_host)

        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        instance = mock.sentinel.instance
        instance.uuid = uuids.instance
        libvirt_driver.connect_volume(connection_info, self.disk_info,
                                      instance)
        libvirt_driver.disconnect_volume(connection_info, "vde",
                                         mock.sentinel.instance)

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(connection_info['data']['device_path'], device_path)
        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', export_string, export_mnt_base),
            ('umount', export_mnt_base),
            ('rmdir', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_nfs_driver_get_config(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_host)
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

    def test_libvirt_nfs_driver_with_opts(self):
        libvirt_driver = nfs.LibvirtNFSVolumeDriver(self.fake_host)
        export_string = '192.168.1.1:/nfs/share1'
        options = '-o intr,nfsvers=3'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}
        instance = mock.sentinel.instance
        instance.uuid = uuids.instance
        libvirt_driver.connect_volume(connection_info, self.disk_info,
                                      instance)
        libvirt_driver.disconnect_volume(connection_info, "vde",
                                         mock.sentinel.instance)

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', '-o', 'intr,nfsvers=3',
             export_string, export_mnt_base),
            ('umount', export_mnt_base),
            ('rmdir', export_mnt_base)
        ]
        self.assertEqual(expected_commands, self.executes)
