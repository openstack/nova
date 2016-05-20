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

import nova.exception
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import scality


class LibvirtScalityVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def setUp(self):
        super(LibvirtScalityVolumeDriverTestCase, self).setUp()

        self.scality_sofs_config = 'fake.conf'
        self.scality_sofs_mount_point = '/fake'
        self.flags(scality_sofs_config=self.scality_sofs_config,
                   scality_sofs_mount_point=self.scality_sofs_mount_point,
                   group='libvirt')

        self.drv = scality.LibvirtScalityVolumeDriver(self.fake_conn)

    @mock.patch('six.moves.urllib.request.urlopen')
    def test_connect_volume(self, mock_urlopen):
        TEST_VOLDIR = 'volumes'
        TEST_VOLNAME = 'volume_name'
        TEST_CONN_INFO = {
            'data': {
                'sofs_path': os.path.join(TEST_VOLDIR, TEST_VOLNAME)
            }
        }
        TEST_VOLPATH = os.path.join(self.scality_sofs_mount_point,
                                    TEST_VOLDIR,
                                    TEST_VOLNAME)

        def _access_wrapper(path, flags):
            if path == '/sbin/mount.sofs':
                return True
            else:
                return os.access(path, flags)

        self.stub_out('os.access', _access_wrapper)

        with mock.patch.object(self.drv, '_mount_sofs'):
            self.drv.connect_volume(TEST_CONN_INFO, self.disk_info)

        device_path = os.path.join(self.scality_sofs_mount_point,
                                   TEST_CONN_INFO['data']['sofs_path'])
        self.assertEqual(TEST_CONN_INFO['data']['device_path'], device_path)

        conf = self.drv.get_config(TEST_CONN_INFO, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, TEST_VOLPATH)

    @mock.patch('nova.utils.execute')
    def test_mount_sofs_when_sofs_already_mounted(self, mock_execute):
        with mock.patch.object(self.drv, '_sofs_is_mounted') as m_is_mounted:
            m_is_mounted.return_value = True

            self.drv._mount_sofs()

        mock_execute.assert_called_once_with('mkdir', '-p',
                                             self.scality_sofs_mount_point)
        self.assertEqual(1, m_is_mounted.call_count)

    @mock.patch('nova.utils.execute', mock.Mock())
    def test_mount_sofs_when_mount_fails(self):
        with mock.patch.object(self.drv, '_sofs_is_mounted') as m_is_mounted:
            m_is_mounted.side_effect = [False, False]

            self.assertRaises(nova.exception.NovaException,
                              self.drv._mount_sofs)

        self.assertEqual(2, m_is_mounted.call_count)

    @mock.patch('nova.utils.execute')
    def test_mount_sofs_when_sofs_is_not_mounted(self, mock_execute):
        with mock.patch.object(self.drv, '_sofs_is_mounted') as m_is_mounted:
            m_is_mounted.side_effect = [False, True]

            self.drv._mount_sofs()

        self.assertEqual(2, m_is_mounted.call_count)
        self.assertEqual(2, mock_execute.call_count)
        expected_calls = [
            mock.call('mkdir', '-p', self.scality_sofs_mount_point),
            mock.call('mount', '-t', 'sofs', self.scality_sofs_config,
                      self.scality_sofs_mount_point, run_as_root=True)
        ]
        mock_execute.assert_has_calls(expected_calls)

    def test_sofs_is_mounted_when_sofs_is_not_mounted(self):
        mock_open = mock.mock_open(read_data='tmpfs /dev/shm\n')
        with mock.patch('io.open', mock_open) as mock_open:
            self.assertFalse(self.drv._sofs_is_mounted())

    def test_sofs_is_mounted_when_sofs_is_mounted(self):
        proc_mount = '/dev/fuse ' + self.scality_sofs_mount_point + '\n'
        mock_open = mock.mock_open(read_data=proc_mount)
        with mock.patch('io.open', mock_open) as mock_open:
            self.assertTrue(self.drv._sofs_is_mounted())
