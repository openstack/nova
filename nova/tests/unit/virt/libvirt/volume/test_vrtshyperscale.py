# Copyright (c) 2017 Veritas Technologies LLC
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

import mock

from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import vrtshyperscale

DEVICE_NAME = '{8ee71c33-dcd0-4267-8f2b-e0742ecabe9f}'
DEVICE_PATH = '/dev/8ee71c33-dcd0-4267-8f2b-e0742ec'


class LibvirtHyperScaleVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_driver_init(self):
        hs = vrtshyperscale.LibvirtHyperScaleVolumeDriver(self.fake_host)
        self.assertIsInstance(hs.connector, connector.HyperScaleConnector)

    def test_get_config(self):
        hs = vrtshyperscale.LibvirtHyperScaleVolumeDriver(self.fake_host)

        # expect valid conf is returned if called with proper arguments
        disk_info = {'name': DEVICE_NAME,
                     'type': None,
                     'dev': None,
                     'bus': None,
                     'device_path': DEVICE_PATH,
                    }
        conn = {'data': disk_info}

        conf = hs.get_config(conn, disk_info)

        self.assertEqual("block", conf.source_type)
        self.assertEqual(DEVICE_PATH, conf.source_path)

    @mock.patch('os_brick.initiator.connectors.vrtshyperscale'
                '.HyperScaleConnector.connect_volume')
    def test_connect_volume(self, mock_brick_connect_volume):
        mock_brick_connect_volume.return_value = {'path': DEVICE_PATH}

        hs = vrtshyperscale.LibvirtHyperScaleVolumeDriver(self.fake_host)

        # dummy arguments are just passed through to mock connector
        disk_info = {'name': DEVICE_NAME}
        connection_info = {'data': disk_info}

        hs.connect_volume(connection_info, mock.sentinel.instance)

        # expect connect_volume to add device_path to connection_info:
        self.assertEqual(connection_info['data']['device_path'], DEVICE_PATH)

    @mock.patch('os_brick.initiator.connectors.vrtshyperscale'
                '.HyperScaleConnector.disconnect_volume')
    def test_disconnect_volume(self, mock_brick_disconnect_volume):
        mock_brick_disconnect_volume.return_value = None

        hs = vrtshyperscale.LibvirtHyperScaleVolumeDriver(self.fake_host)

        # dummy arguments are just passed through to mock connector
        conn_data = {'name': DEVICE_NAME}
        connection_info = {'data': conn_data}

        hs.disconnect_volume(connection_info, mock.sentinel.instance)

        hs.connector.disconnect_volume.assert_called_once_with(conn_data, None)
