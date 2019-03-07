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

import mock
from os_brick import exception as os_brick_exception
from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import iscsi


class LibvirtISCSIVolumeDriverTestCase(
        test_volume.LibvirtISCSIVolumeBaseTestCase):

    def test_libvirt_iscsi_driver(self, transport=None):
        for multipath in (True, False):
            self.flags(volume_use_multipath=multipath, group='libvirt')
            libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_host)
            self.assertIsInstance(libvirt_driver.connector,
                                  connector.ISCSIConnector)
            if hasattr(libvirt_driver.connector, 'use_multipath'):
                self.assertEqual(
                    multipath, libvirt_driver.connector.use_multipath)

    def test_libvirt_iscsi_driver_get_config(self):
        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_host)

        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self.assertEqual('block', tree.get('type'))
        self.assertEqual(device_path, tree.find('./source').get('dev'))
        self.assertEqual('raw', tree.find('./driver').get('type'))
        self.assertEqual('native', tree.find('./driver').get('io'))

    @mock.patch.object(iscsi.LOG, 'warning')
    def test_libvirt_iscsi_driver_disconnect_volume_with_devicenotfound(self,
            mock_LOG_warning):
        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_host)
        libvirt_driver.connector.disconnect_volume = mock.MagicMock(
            side_effect=os_brick_exception.VolumeDeviceNotFound(
                device=device_path))
        libvirt_driver.disconnect_volume(connection_info,
                                         mock.sentinel.instance)

        msg = mock_LOG_warning.call_args_list[0]
        self.assertIn('Ignoring VolumeDeviceNotFound', msg[0][0])

    def test_extend_volume(self):
        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}
        requested_size = 1

        libvirt_driver = iscsi.LibvirtISCSIVolumeDriver(self.fake_host)
        libvirt_driver.connector.extend_volume = mock.MagicMock(
            return_value=requested_size)
        new_size = libvirt_driver.extend_volume(connection_info,
                                                mock.sentinel.instance,
                                                requested_size)

        self.assertEqual(requested_size, new_size)
        libvirt_driver.connector.extend_volume.assert_called_once_with(
           connection_info['data'])
