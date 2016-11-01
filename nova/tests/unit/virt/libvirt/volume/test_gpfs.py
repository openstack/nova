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


from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import gpfs


class LibvirtGPFSVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_gpfs_driver_get_config(self):
        libvirt_driver = gpfs.LibvirtGPFSVolumeDriver(self.fake_host)
        connection_info = {
            'driver_volume_type': 'gpfs',
            'data': {
                'device_path': '/gpfs/foo',
            },
            'serial': 'fake_serial',
        }
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('file', tree.get('type'))
        self.assertEqual('fake_serial', tree.find('./serial').text)
