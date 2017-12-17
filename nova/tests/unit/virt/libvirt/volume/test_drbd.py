# Copyright (c) 2015 LINBIT HA-Solutions GmbH.
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
"""Unit tests for the DRDB volume driver module."""

import mock
from os_brick.initiator import connector

from nova import context as nova_context
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import drbd


class LibvirtDRBDVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):
    """Tests the LibvirtDRBDVolumeDriver class."""

    def test_libvirt_drbd_driver(self):
        drbd_driver = drbd.LibvirtDRBDVolumeDriver(self.fake_host)
        self.assertIsInstance(drbd_driver.connector, connector.DRBDConnector)
        # connect a fake volume
        connection_info = {
            'data': {
                'device': '/path/to/fake-device'
            }
        }
        ctxt = nova_context.RequestContext('fake-user', 'fake-project')
        instance = fake_instance.fake_instance_obj(ctxt)
        device_info = {
            'type': 'block',
            'path': connection_info['data']['device'],
        }
        with mock.patch.object(connector.DRBDConnector, 'connect_volume',
                               return_value=device_info):
            drbd_driver.connect_volume(connection_info, instance)
        # assert that the device_path was set
        self.assertIn('device_path', connection_info['data'])
        self.assertEqual('/path/to/fake-device',
                         connection_info['data']['device_path'])
        # now get the config using the updated connection_info
        conf = drbd_driver.get_config(connection_info, self.disk_info)
        # assert things were passed through to the parent class
        self.assertEqual('block', conf.source_type)
        self.assertEqual('/path/to/fake-device', conf.source_path)
        # now disconnect the volume
        with mock.patch.object(connector.DRBDConnector,
                               'disconnect_volume') as mock_disconnect:
            drbd_driver.disconnect_volume(connection_info, instance)
        # disconnect is all passthrough so just assert the call
        mock_disconnect.assert_called_once_with(connection_info['data'], None)
