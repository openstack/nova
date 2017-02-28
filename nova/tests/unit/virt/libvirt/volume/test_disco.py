#    Copyright (c) 2015 Industrial Technology Research Institute.
#    All Rights Reserved.
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

import mock
from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import disco


class LibvirtDISCOVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_disco_driver(self):
        libvirt_driver = disco.LibvirtDISCOVolumeDriver(
            self.fake_host)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.DISCOConnector)

    def test_libvirt_disco_driver_connect(self):
        dcon = disco.LibvirtDISCOVolumeDriver(self.fake_host)
        conf = {'server_ip': '127.0.0.1', 'server_port': 9898}
        disk_info = {'disco_id': '1234567',
                     'name': 'aDiscoVolume',
                     'conf': conf}
        conn = {'data': disk_info}
        with mock.patch.object(dcon.connector,
                               'connect_volume',
                               return_value={'path': '/dev/dms1234567'}):
            dcon.connect_volume(conn, None, mock.sentinel.instance)
            self.assertEqual('/dev/dms1234567',
                             conn['data']['device_path'])

    def test_libvirt_disco_driver_get_config(self):
        dcon = disco.LibvirtDISCOVolumeDriver(self.fake_host)

        disk_info = {'path': '/dev/dms1234567', 'name': 'aDiscoVolume',
                     'type': 'raw', 'dev': 'vda1', 'bus': 'pci0',
                     'device_path': '/dev/dms1234567'}
        conn = {'data': disk_info}
        conf = dcon.get_config(conn, disk_info)
        self.assertEqual('file', conf.source_type)
        self.assertEqual('/dev/dms1234567', conf.source_path)
        self.assertEqual('disco', conf.source_protocol)

    def test_libvirt_disco_driver_disconnect(self):
        dcon = disco.LibvirtDISCOVolumeDriver(self.fake_host)
        dcon.connector.disconnect_volume = mock.MagicMock()
        disk_info = {'path': '/dev/dms1234567', 'name': 'aDiscoVolume',
                     'type': 'raw', 'dev': 'vda1', 'bus': 'pci0',
                     'device_path': '/dev/dms123456'}
        conn = {'data': disk_info}
        dcon.disconnect_volume(conn, disk_info, mock.sentinel.instance)
        dcon.connector.disconnect_volume.assert_called_once_with(
            disk_info, None)
