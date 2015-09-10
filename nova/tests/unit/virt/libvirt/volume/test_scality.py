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

import fixtures

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import scality


class LibvirtScalityVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_scality_driver(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        TEST_MOUNT = os.path.join(tempdir, 'fake_mount')
        TEST_CONFIG = os.path.join(tempdir, 'fake_config')
        TEST_VOLDIR = 'volumes'
        TEST_VOLNAME = 'volume_name'
        TEST_CONN_INFO = {
            'data': {
                'sofs_path': os.path.join(TEST_VOLDIR, TEST_VOLNAME)
            }
        }
        TEST_VOLPATH = os.path.join(TEST_MOUNT,
                                    TEST_VOLDIR,
                                    TEST_VOLNAME)
        open(TEST_CONFIG, "w+").close()
        os.makedirs(os.path.join(TEST_MOUNT, 'sys'))

        def _access_wrapper(path, flags):
            if path == '/sbin/mount.sofs':
                return True
            else:
                return os.access(path, flags)

        self.stubs.Set(os, 'access', _access_wrapper)
        self.flags(scality_sofs_config=TEST_CONFIG,
                   scality_sofs_mount_point=TEST_MOUNT,
                   group='libvirt')
        driver = scality.LibvirtScalityVolumeDriver(self.fake_conn)
        driver.connect_volume(TEST_CONN_INFO, self.disk_info)

        device_path = os.path.join(TEST_MOUNT,
                                   TEST_CONN_INFO['data']['sofs_path'])
        self.assertEqual(TEST_CONN_INFO['data']['device_path'], device_path)

        conf = driver.get_config(TEST_CONN_INFO, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, TEST_VOLPATH)
