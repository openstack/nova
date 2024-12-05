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
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.unit.virt.libvirt.volume import test_mount
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova import utils
from nova.virt.libvirt.volume import cephfs
from nova.virt.libvirt.volume import mount


class LibvirtCEPHFSVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    """Tests the libvirt CEPHFS volume driver."""

    def setUp(self):
        super(LibvirtCEPHFSVolumeDriverTestCase, self).setUp()

        self.useFixture(test_mount.MountFixture(self))

        m = mount.get_manager()
        m._reset_state()

        self.mnt_base = '/mnt'
        m.host_up(self.fake_host)
        self.flags(ceph_mount_point_base=self.mnt_base, group='libvirt')

    def test_libvirt_ceph_driver(self):
        libvirt_driver = cephfs.LibvirtCEPHFSVolumeDriver(self.fake_host)

        export_string = '192.168.1.1:/ceph/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {
            "data": {
                "export": export_string,
                "name": self.name,
                "options": ["name=myname", "secret=mysecret"],
            }
        }
        instance = mock.sentinel.instance
        instance.uuid = uuids.instance
        libvirt_driver.connect_volume(connection_info, instance)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(connection_info['data']['device_path'], device_path)
        self.mock_ensure_tree.assert_has_calls([mock.call(export_mnt_base)])
        self.mock_mount.assert_has_calls(
            [
                mock.call(
                    "ceph",
                    export_string,
                    export_mnt_base,
                    ["-o", "name=myname,secret=mysecret"],
                )
            ]
        )
        self.mock_umount.assert_has_calls([mock.call(export_mnt_base)])
        self.mock_rmdir.assert_has_calls([mock.call(export_mnt_base)])

    def test_libvirt_ceph_driver_with_default_options(self):
        libvirt_driver = cephfs.LibvirtCEPHFSVolumeDriver(self.fake_host)
        self.flags(
            ceph_mount_options=["default_opt1=true", "default_opt2=true"],
            group="libvirt",
        )

        export_string = '192.168.1.1:/ceph/share1'
        export_mnt_base = os.path.join(self.mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {
            "data": {
                "export": export_string,
                "name": self.name,
                "options": ["name=myname", "secret=mysecret"],
            }
        }
        instance = mock.sentinel.instance
        instance.uuid = uuids.instance
        libvirt_driver.connect_volume(connection_info, instance)
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(connection_info['data']['device_path'], device_path)
        self.mock_ensure_tree.assert_has_calls([mock.call(export_mnt_base)])
        self.mock_mount.assert_has_calls(
            [
                mock.call(
                    "ceph",
                    export_string,
                    export_mnt_base,
                    [
                        "-o",
                        "default_opt1=true,default_opt2=true,name=myname,"
                        "secret=mysecret",
                    ],
                )
            ]
        )
        self.mock_umount.assert_has_calls([mock.call(export_mnt_base)])
        self.mock_rmdir.assert_has_calls([mock.call(export_mnt_base)])
