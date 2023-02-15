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

from unittest import mock

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import lightos

from os_brick import initiator


class LibvirtLightVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):

    @mock.patch('nova.utils.get_root_helper')
    @mock.patch('os_brick.initiator.connector.InitiatorConnector.factory')
    def test_libvirt_lightos_driver(self, mock_factory, mock_helper):
        mock_helper.return_value = 'sudo'
        lightos.LibvirtLightOSVolumeDriver(self.fake_host)
        mock_factory.assert_called_once_with(
            initiator.LIGHTOS, root_helper='sudo',
            device_scan_attempts=5)

    @mock.patch('os_brick.initiator.connector.InitiatorConnector.factory',
        new=mock.Mock())
    def test_libvirt_lightos_driver_connect(self):
        lightos_driver = lightos.LibvirtLightOSVolumeDriver(
            self.fake_host)
        config = {'server_ip': '127.0.0.1', 'server_port': 9898}
        disk_info = {
            'id': '1234567',
            'name': 'aLightVolume',
            'conf': config}
        connection_info = {'data': disk_info}
        lightos_driver.connector.connect_volume.return_value = (
            {'path': '/dev/dms1234567'})

        lightos_driver.connect_volume(connection_info, None)

        lightos_driver.connector.connect_volume.assert_called_once_with(
            connection_info['data'])
        self.assertEqual(
            '/dev/dms1234567',
            connection_info['data']['device_path'])

    @mock.patch('os_brick.initiator.connector.InitiatorConnector.factory',
        new=mock.Mock(return_value=mock.Mock()))
    def test_libvirt_lightos_driver_disconnect(self):
        lightos_driver = lightos.LibvirtLightOSVolumeDriver(self.connr)
        disk_info = {
            'path': '/dev/dms1234567', 'name': 'aLightosVolume',
                    'type': 'raw', 'dev': 'vda1', 'bus': 'pci0',
                    'device_path': '/dev/dms123456'}
        connection_info = {'data': disk_info}
        lightos_driver.disconnect_volume(connection_info, None)
        lightos_driver.connector.disconnect_volume.assert_called_once_with(
            disk_info, None, force=False)

        # Verify force=True
        lightos_driver.connector.disconnect_volume.reset_mock()
        lightos_driver.disconnect_volume(connection_info, None, force=True)
        lightos_driver.connector.disconnect_volume.assert_called_once_with(
            disk_info, None, force=True)

    @mock.patch('os_brick.initiator.connector.InitiatorConnector.factory',
        new=mock.Mock(return_value=mock.Mock()))
    def test_libvirt_lightos_driver_get_config(self):
        lightos_driver = lightos.LibvirtLightOSVolumeDriver(self.fake_host)
        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        conf = lightos_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self.assertEqual('block', tree.get('type'))
        self.assertEqual(device_path, tree.find('./source').get('dev'))
        self.assertEqual('raw', tree.find('./driver').get('type'))
