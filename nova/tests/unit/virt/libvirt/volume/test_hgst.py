# Copyright 2015 HGST
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import hgst


# Actual testing of the os_brick HGST driver done in the os_brick testcases
# Here we're concerned only with the small API shim that connects Nova
# so these will be pretty simple cases.


class LibvirtHGSTVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    def test_libvirt_hgst_driver_type(self):
        drvr = hgst.LibvirtHGSTVolumeDriver(self.fake_host)
        self.assertIsInstance(drvr.connector, connector.HGSTConnector)

    def test_libvirt_hgst_driver_connect(self):
        def brick_conn_vol(data):
            return {'path': '/dev/space01'}

        drvr = hgst.LibvirtHGSTVolumeDriver(self.fake_host)
        drvr.connector.connect_volume = brick_conn_vol
        di = {'path': '/dev/space01', 'name': 'space01'}
        ci = {'data': di}
        drvr.connect_volume(ci, mock.sentinel.instance)
        self.assertEqual('/dev/space01',
                         ci['data']['device_path'])

    def test_libvirt_hgst_driver_get_config(self):
        drvr = hgst.LibvirtHGSTVolumeDriver(self.fake_host)
        di = {'path': '/dev/space01', 'name': 'space01', 'type': 'raw',
              'dev': 'vda1', 'bus': 'pci0', 'device_path': '/dev/space01'}
        ci = {'data': di}
        conf = drvr.get_config(ci, di)
        self.assertEqual('block', conf.source_type)
        self.assertEqual('/dev/space01', conf.source_path)

    def test_libvirt_hgst_driver_disconnect(self):
        drvr = hgst.LibvirtHGSTVolumeDriver(self.fake_host)
        drvr.connector.disconnect_volume = mock.MagicMock()
        ci = {'data': mock.sentinel.conn_data}
        drvr.disconnect_volume(ci, mock.sentinel.instance)
        drvr.connector.disconnect_volume.assert_called_once_with(
                       mock.sentinel.conn_data, None)
