# Copyright 2015 IBM Corp.
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

import os

import mock

from nova import test
from nova import utils
from nova.virt.libvirt.volume import fs

FAKE_MOUNT_POINT = '/var/lib/nova/fake-mount'
FAKE_SHARE = 'fake-share'
NORMALIZED_SHARE = FAKE_SHARE + '-normalized'
HASHED_SHARE = utils.get_hash_str(NORMALIZED_SHARE)
FAKE_DEVICE_NAME = 'fake-device'


class FakeFileSystemVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):

    def _get_mount_point_base(self):
        return FAKE_MOUNT_POINT

    def _normalize_export(self, export):
        return NORMALIZED_SHARE


class LibvirtBaseFileSystemVolumeDriverTestCase(test.NoDBTestCase):
    """Tests the basic behavior of the LibvirtBaseFileSystemVolumeDriver"""

    def setUp(self):
        super(LibvirtBaseFileSystemVolumeDriverTestCase, self).setUp()
        self.connection = mock.Mock()
        self.driver = FakeFileSystemVolumeDriver(self.connection)
        self.connection_info = {
            'data': {
                'export': FAKE_SHARE,
                'name': FAKE_DEVICE_NAME,
            }
        }

    def test_get_device_path(self):
        path = self.driver._get_device_path(self.connection_info)
        expected_path = os.path.join(FAKE_MOUNT_POINT,
                                     HASHED_SHARE,
                                     FAKE_DEVICE_NAME)
        self.assertEqual(expected_path, path)
