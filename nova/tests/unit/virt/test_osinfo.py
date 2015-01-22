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

import mock

from nova import exception
from nova import objects
from nova import test
from nova.virt import osinfo


class LibvirtOsInfoTest(test.NoDBTestCase):

    def setUp(self):
        super(LibvirtOsInfoTest, self).setUp()
        image_meta = {'properties':
                            {'os_distro': 'fedora19',
                             'hw_disk_bus': 'ide',
                             'hw_vif_model': 'virtio'}
                        }
        self.img_meta = objects.ImageMeta.from_dict(image_meta)
        osinfo.libosinfo = mock.Mock()

    def test_get_os(self):
        filter_mock = mock.Mock()
        osinfo.libosinfo = mock.Mock()
        osinfo.libosinfo.Filter.new.return_value = filter_mock
        osinfo_mock = mock.Mock()
        filtered_list = osinfo_mock.new_filtered
        filtered_list.return_value.get_length.return_value = 1
        os_info_db = osinfo._OsInfoDatabase.get_instance()
        os_info_db.oslist = osinfo_mock
        os_info_db.get_os('test33')
        filter_mock.add_constraint.assert_called_once_with('short-id',
                                                           'test33')
        self.assertTrue(filtered_list.return_value.get_nth.called)

    def test_get_os_fails(self):
        filter_mock = mock.Mock()
        osinfo.libosinfo = mock.Mock()
        osinfo.libosinfo.Filter.return_value.new.return_value = filter_mock
        osinfo_mock = mock.Mock()
        filtered = osinfo_mock.new_filtered.return_value
        filtered.get_length.return_value = 0
        os_info_db = osinfo._OsInfoDatabase.get_instance()
        os_info_db.oslist = osinfo_mock
        self.assertRaises(exception.OsInfoNotFound,
                          os_info_db.get_os,
                          'test33')

    def test_hardware_properties_from_osinfo(self):
        """Verifies that HardwareProperties attributes are being set
           from libosinfo.
        """
        img_meta = {'properties':
                       {'os_distro': 'fedora19'}
                   }

        img_meta = objects.ImageMeta.from_dict(img_meta)
        with test.nested(
            mock.patch.object(osinfo.OsInfo, 'network_model',
                               new_callable=mock.PropertyMock,
                               return_value='rtl8139'),
            mock.patch.object(osinfo.OsInfo, 'disk_model',
                               new_callable=mock.PropertyMock,
                               return_value='scsi')):

            osinfo_obj = osinfo.HardwareProperties(img_meta)
            self.assertEqual('rtl8139', osinfo_obj.network_model)
            self.assertEqual('scsi', osinfo_obj.disk_model)

    def test_hardware_properties_from_meta(self):
        """Verifies that HardwareProperties attributes are being set
           from image properties.
        """
        with mock.patch.object(osinfo._OsInfoDatabase, 'get_instance'):
            osinfo_obj = osinfo.HardwareProperties(self.img_meta)
            self.assertEqual('virtio', osinfo_obj.network_model)
            self.assertEqual('ide', osinfo_obj.disk_model)
