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
from oslo_serialization import jsonutils

from nova import objects
from nova.tests.unit.objects import test_objects

fake_net_interface_meta = objects.NetworkInterfaceMetadata(
                            mac='52:54:00:f6:35:8f',
                            tags=['mytag1'],
                            bus=objects.PCIDeviceBus(address='0000:00:03.0'),
                            vlan=1000)
fake_pci_disk_meta = objects.DiskMetadata(
                            bus=objects.PCIDeviceBus(address='0000:00:09.0'),
                            tags=['nfvfunc3'])
fake_obj_devices_metadata = objects.InstanceDeviceMetadata(
                         devices=[fake_net_interface_meta, fake_pci_disk_meta])

fake_devices_metadata = fake_obj_devices_metadata._to_json()

fake_db_metadata = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'device_metadata': fake_obj_devices_metadata._to_json()
    }

fake_old_db_metadata = dict(fake_db_metadata)  # copy
fake_old_db_metadata['device_metadata'] = jsonutils.dumps(
                                                         fake_devices_metadata)


def get_fake_obj_device_metadata(context):
    fake_obj_devices_metadata_cpy = fake_obj_devices_metadata.obj_clone()
    fake_obj_devices_metadata_cpy._context = context
    return fake_obj_devices_metadata_cpy


class _TestInstanceDeviceMetadata(object):
    def _check_object(self, obj_meta):
        self.assertTrue(isinstance(obj_meta,
                                   objects.NetworkInterfaceMetadata) or
                        isinstance(obj_meta, objects.DiskMetadata))
        if isinstance(obj_meta, objects.NetworkInterfaceMetadata):
            self.assertEqual(obj_meta.mac, '52:54:00:f6:35:8f')
            self.assertEqual(obj_meta.tags, ['mytag1'])
            self.assertIsInstance(obj_meta.bus, objects.PCIDeviceBus)
            self.assertEqual(obj_meta.bus.address, '0000:00:03.0')
            self.assertEqual(obj_meta.vlan, 1000)
        elif isinstance(obj_meta, objects.DiskMetadata):
            self.assertIsInstance(obj_meta.bus, objects.PCIDeviceBus)
            self.assertEqual(obj_meta.bus.address, '0000:00:09.0')
            self.assertEqual(obj_meta.tags, ['nfvfunc3'])

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_db_metadata
        inst_meta = objects.InstanceDeviceMetadata
        dev_meta = inst_meta.get_by_instance_uuid(
            self.context, 'fake_uuid')
        for obj_meta, fake_meta in zip(
                dev_meta.devices,
                fake_obj_devices_metadata.devices):
            self._check_object(obj_meta)

    def test_obj_from_db(self):
        db_meta = fake_db_metadata['device_metadata']
        metadata = objects.InstanceDeviceMetadata.obj_from_db(None, db_meta)
        for obj_meta in metadata.devices:
            self._check_object(obj_meta)

    def test_net_if_compatible_pre_1_1(self):
        vif_obj = objects.NetworkInterfaceMetadata(mac='52:54:00:f6:35:8f')
        vif_obj.tags = ['test']
        vif_obj.vlan = 1000
        primitive = vif_obj.obj_to_primitive()
        self.assertIn('vlan', primitive['nova_object.data'])
        vif_obj.obj_make_compatible(primitive['nova_object.data'], '1.0')
        self.assertNotIn('vlan', primitive['nova_object.data'])


class TestInstanceDeviceMetadata(test_objects._LocalTest,
                               _TestInstanceDeviceMetadata):
    pass


class TestInstanceDeviceMetadataRemote(test_objects._RemoteTest,
                                     _TestInstanceDeviceMetadata):
    pass
