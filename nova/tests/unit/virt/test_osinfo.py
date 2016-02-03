# Copyright 2015 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures
import mock

from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.virt import fakelibosinfo
from nova.virt import osinfo


class LibvirtOsInfoTest(test.NoDBTestCase):

    def setUp(self):
        super(LibvirtOsInfoTest, self).setUp()
        image_meta = {'properties':
                            {'os_distro': 'fedora22',
                             'hw_disk_bus': 'ide',
                             'hw_vif_model': 'rtl8139'}
                        }
        self.img_meta = objects.ImageMeta.from_dict(image_meta)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.osinfo.libosinfo',
            fakelibosinfo))

    def test_get_os(self):
        os_info_db = osinfo._OsInfoDatabase.get_instance()
        os_name = os_info_db.get_os('fedora22').get_name()
        self.assertTrue('Fedora 22', os_name)

    def test_get_os_fails(self):
        os_info_db = osinfo._OsInfoDatabase.get_instance()
        self.assertRaises(exception.OsInfoNotFound,
                          os_info_db.get_os,
                          'test33')

    def test_hardware_properties_from_osinfo(self):
        """Verifies that HardwareProperties attributes are being set
           from libosinfo.
        """
        img_meta = {'properties':
                       {'os_distro': 'fedora22'}
                   }

        img_meta = objects.ImageMeta.from_dict(img_meta)
        osinfo_obj = osinfo.HardwareProperties(img_meta)
        self.assertEqual('virtio', osinfo_obj.network_model)
        self.assertEqual('virtio', osinfo_obj.disk_model)

    def test_hardware_properties_from_meta(self):
        """Verifies that HardwareProperties attributes are being set
           from image properties.
        """
        with mock.patch.object(osinfo._OsInfoDatabase, 'get_instance'):
            osinfo_obj = osinfo.HardwareProperties(self.img_meta)
            self.assertEqual('rtl8139', osinfo_obj.network_model)
            self.assertEqual('ide', osinfo_obj.disk_model)
