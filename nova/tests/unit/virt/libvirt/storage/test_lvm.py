# Copyright 2012 NTT Data. All Rights Reserved.
# Copyright 2012 Yahoo! Inc. All Rights Reserved.
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
from oslo_concurrency import processutils
from oslo_config import cfg

from nova import exception
from nova import test
from nova import utils
from nova.virt.libvirt.storage import lvm
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


class LvmTestCase(test.NoDBTestCase):
    @mock.patch('nova.utils.execute')
    def test_get_volume_size(self, mock_execute):
        mock_execute.return_value = 123456789, None
        size = lvm.get_volume_size('/dev/foo')
        mock_execute.assert_has_calls(
            [mock.call('blockdev', '--getsize64', '/dev/foo',
                       run_as_root=True)])
        self.assertEqual(123456789, size)

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                            stderr=('blockdev: cannot open /dev/foo: '
                                    'No such device or address')))
    def test_get_volume_size_not_found(self, mock_execute):
        self.assertRaises(exception.VolumeBDMPathNotFound,
                          lvm.get_volume_size, '/dev/foo')

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                            stderr=('blockdev: cannot open /dev/foo: '
                                    'No such file or directory')))
    def test_get_volume_size_not_found_file(self, mock_execute):
        self.assertRaises(exception.VolumeBDMPathNotFound,
            lvm.get_volume_size, '/dev/foo')

    @mock.patch.object(libvirt_utils, 'path_exists', return_value=True)
    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                            stderr='blockdev: i am sad in other ways'))
    def test_get_volume_size_unexpectd_error(self, mock_execute,
                                             mock_path_exists):
        self.assertRaises(processutils.ProcessExecutionError,
                          lvm.get_volume_size, '/dev/foo')

    @mock.patch('nova.utils.execute')
    def test_lvm_clear(self, mock_execute):
        def fake_lvm_size(path):
            return lvm_size

        self.stub_out('nova.virt.libvirt.storage.lvm.get_volume_size',
                      fake_lvm_size)

        # Test the correct dd commands are run for various sizes
        lvm_size = 1
        lvm.clear_volume('/dev/v1')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v1',
                       'seek=0', 'count=1', 'conv=fdatasync',
                       run_as_root=True)])
        mock_execute.reset_mock()

        lvm_size = 1024
        lvm.clear_volume('/dev/v2')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v2',
                       'seek=0', 'count=1', 'conv=fdatasync',
                       run_as_root=True)])
        mock_execute.reset_mock()

        lvm_size = 1025
        lvm.clear_volume('/dev/v3')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v3',
                       'seek=0', 'count=1', 'conv=fdatasync',
                       run_as_root=True),
             mock.call('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v3',
                       'seek=1024', 'count=1', 'conv=fdatasync',
                       run_as_root=True)])
        mock_execute.reset_mock()

        lvm_size = 1048576
        lvm.clear_volume('/dev/v4')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v4',
                       'seek=0', 'count=1', 'oflag=direct',
                       run_as_root=True)])
        mock_execute.reset_mock()

        lvm_size = 1048577
        lvm.clear_volume('/dev/v5')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v5',
                       'seek=0', 'count=1', 'oflag=direct',
                       run_as_root=True),
             mock.call('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v5',
                       'seek=1048576', 'count=1', 'conv=fdatasync',
                       run_as_root=True)])
        mock_execute.reset_mock()

        lvm_size = 1234567
        lvm.clear_volume('/dev/v6')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v6',
                       'seek=0', 'count=1', 'oflag=direct',
                       run_as_root=True),
             mock.call('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v6',
                       'seek=1024', 'count=181', 'conv=fdatasync',
                       run_as_root=True),
             mock.call('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v6',
                       'seek=1233920', 'count=647', 'conv=fdatasync',
                       run_as_root=True)])
        mock_execute.reset_mock()

        # Test volume_clear_size limits the size
        lvm_size = 10485761
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm.clear_volume('/dev/v7')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v7',
                       'seek=0', 'count=1', 'oflag=direct',
                       run_as_root=True)])
        mock_execute.reset_mock()

        CONF.set_override('volume_clear_size', '2', 'libvirt')
        lvm_size = 1048576
        lvm.clear_volume('/dev/v9')
        mock_execute.assert_has_calls(
            [mock.call('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v9',
                              'seek=0', 'count=1', 'oflag=direct',
                       run_as_root=True)])
        mock_execute.reset_mock()

        # Test volume_clear=shred
        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '0', 'libvirt')
        lvm_size = 1048576
        lvm.clear_volume('/dev/va')
        mock_execute.assert_has_calls(
            [mock.call('shred', '-n3', '-s1048576', '/dev/va',
                       run_as_root=True)])
        mock_execute.reset_mock()

        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm_size = 10485761
        lvm.clear_volume('/dev/vb')
        mock_execute.assert_has_calls(
            [mock.call('shred', '-n3', '-s1048576', '/dev/vb',
                       run_as_root=True)])
        mock_execute.reset_mock()

        # Test volume_clear=none does nothing
        CONF.set_override('volume_clear', 'none', 'libvirt')
        lvm.clear_volume('/dev/vc')
        mock_execute.assert_not_called()

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                                    stderr=('blockdev: cannot open /dev/foo: '
                                            'No such file or directory')))
    def test_lvm_clear_ignore_lvm_not_found(self, mock_execute):
        lvm.clear_volume('/dev/foo')

    @mock.patch.object(lvm, 'clear_volume')
    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError('Error'))
    def test_fail_remove_all_logical_volumes(self, mock_clear, mock_execute):
        self.assertRaises(exception.VolumesNotRemoved,
                          lvm.remove_volumes,
                          ['vol1', 'vol2', 'vol3'])
        self.assertEqual(3, mock_execute.call_count)
