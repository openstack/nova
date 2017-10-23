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
from oslo_utils import units

from nova import exception
from nova import test
from nova.virt.libvirt.storage import lvm

CONF = cfg.CONF


class LvmTestCase(test.NoDBTestCase):
    @mock.patch('nova.privsep.fs.blockdev_size')
    def test_get_volume_size(self, mock_blockdev_size):
        mock_blockdev_size.return_value = '123456789', None
        size = lvm.get_volume_size('/dev/foo')
        self.assertEqual(123456789, size)

    @mock.patch('nova.privsep.fs.blockdev_size',
                side_effect=processutils.ProcessExecutionError(
                    stderr=('blockdev: cannot open /dev/foo: '
                            'No such device or address')))
    def test_get_volume_size_not_found(self, mock_blockdev_size):
        self.assertRaises(exception.VolumeBDMPathNotFound,
                          lvm.get_volume_size, '/dev/foo')

    @mock.patch('nova.privsep.fs.blockdev_size',
                side_effect=processutils.ProcessExecutionError(
                    stderr=('blockdev: cannot open /dev/foo: '
                            'No such file or directory')))
    def test_get_volume_size_not_found_file(self, mock_blockdev_size):
        self.assertRaises(exception.VolumeBDMPathNotFound,
            lvm.get_volume_size, '/dev/foo')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.privsep.fs.blockdev_size',
                side_effect=processutils.ProcessExecutionError(
                    stderr='blockdev: i am sad in other ways'))
    def test_get_volume_size_unexpected_error(self, mock_blockdev_size,
                                              mock_path_exists):
        self.assertRaises(processutils.ProcessExecutionError,
                          lvm.get_volume_size, '/dev/foo')

    @mock.patch('nova.privsep.fs.clear')
    def test_lvm_clear(self, mock_clear):
        def fake_lvm_size(path):
            return lvm_size

        self.stub_out('nova.virt.libvirt.storage.lvm.get_volume_size',
                      fake_lvm_size)

        # Test zeroing volumes works
        CONF.set_override('volume_clear', 'zero', 'libvirt')
        lvm_size = 1024
        lvm.clear_volume('/dev/v1')
        mock_clear.assert_has_calls([
            mock.call('/dev/v1', 1024, shred=False)])
        mock_clear.reset_mock()

        # Test volume_clear_size limits the size
        lvm_size = 10485761
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm.clear_volume('/dev/v7')
        mock_clear.assert_has_calls(
            [mock.call('/dev/v7', 1048576, shred=False)])
        mock_clear.reset_mock()

        CONF.set_override('volume_clear_size', '2', 'libvirt')
        lvm_size = 1048576
        lvm.clear_volume('/dev/v9')
        mock_clear.assert_has_calls(
            [mock.call('/dev/v9', 1048576, shred=False)])
        mock_clear.reset_mock()

        # Test volume_clear=shred
        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '0', 'libvirt')
        lvm_size = 1048576
        lvm.clear_volume('/dev/va')
        mock_clear.assert_has_calls([
            mock.call('/dev/va', 1048576, shred=True)])
        mock_clear.reset_mock()

        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm_size = 10485761
        lvm.clear_volume('/dev/vb')
        mock_clear.assert_has_calls([
            mock.call('/dev/vb', 1 * units.Mi, shred=True)])
        mock_clear.reset_mock()

        # Test volume_clear=none does nothing
        CONF.set_override('volume_clear', 'none', 'libvirt')
        lvm.clear_volume('/dev/vc')
        mock_clear.assert_not_called()

    @mock.patch('nova.privsep.fs.blockdev_size',
                side_effect=processutils.ProcessExecutionError(
                    stderr=('blockdev: cannot open /dev/foo: '
                            'No such file or directory')))
    def test_lvm_clear_ignore_lvm_not_found(self, mock_blockdev_size):
        lvm.clear_volume('/dev/foo')

    @mock.patch.object(lvm, 'clear_volume')
    @mock.patch('nova.privsep.fs.lvremove',
                side_effect=processutils.ProcessExecutionError('Error'))
    def test_fail_remove_all_logical_volumes(self, mock_clear, mock_lvremove):
        self.assertRaises(exception.VolumesNotRemoved,
                          lvm.remove_volumes,
                          ['vol1', 'vol2', 'vol3'])
        self.assertEqual(3, mock_lvremove.call_count)
