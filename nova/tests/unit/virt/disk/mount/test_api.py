# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
from oslo_service import fixture as service_fixture

from nova import test
from nova.virt.disk.mount import api
from nova.virt.disk.mount import block
from nova.virt.disk.mount import loop
from nova.virt.disk.mount import nbd
from nova.virt.image import model as imgmodel


PARTITION = 77
ORIG_DEVICE = "/dev/null"
AUTOMAP_PARTITION = "/dev/nullp77"
MAP_PARTITION = "/dev/mapper/nullp77"


class MountTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MountTestCase, self).setUp()
        # Make RetryDecorator not actually sleep on retries
        self.useFixture(service_fixture.SleepFixture())

    def _test_map_dev(self, partition):
        mount = api.Mount(mock.sentinel.image, mock.sentinel.mount_dir)
        mount.device = ORIG_DEVICE
        mount.partition = partition
        mount.map_dev()
        return mount

    def _exists_effect(self, data):
        def exists_effect(filename):
            try:
                v = data[filename]
                if isinstance(v, list):
                    if len(v) > 0:
                        return v.pop(0)
                    self.fail("Out of items for: %s" % filename)
                return v
            except KeyError:
                self.fail("Unexpected call with: %s" % filename)
        return exists_effect

    def _check_calls(self, exists, filenames, trailing=0):
        self.assertEqual([mock.call(x) for x in filenames],
                exists.call_args_list[:len(filenames)])
        self.assertEqual([mock.call(MAP_PARTITION)] * trailing,
            exists.call_args_list[len(filenames):])

    @mock.patch('os.path.exists')
    def test_map_dev_partition_search(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True})
        mount = self._test_map_dev(-1)
        self._check_calls(exists, [ORIG_DEVICE])
        self.assertNotEqual("", mount.error)
        self.assertFalse(mount.mapped)

    @mock.patch('os.path.exists')
    @mock.patch('nova.privsep.fs.create_device_maps',
                return_value=(None, None))
    def test_map_dev_good(self, mock_create_maps, mock_exists):
        mock_exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: False,
            MAP_PARTITION: [False, True]})
        mount = self._test_map_dev(PARTITION)
        self._check_calls(mock_exists, [ORIG_DEVICE, AUTOMAP_PARTITION], 2)
        self.assertEqual("", mount.error)
        self.assertTrue(mount.mapped)

    @mock.patch('os.path.exists')
    @mock.patch('nova.privsep.fs.create_device_maps',
                return_value=(None, None))
    def test_map_dev_error(self, mock_create_maps, mock_exists):
        mock_exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: False,
            MAP_PARTITION: False})
        mount = self._test_map_dev(PARTITION)
        self._check_calls(mock_exists, [ORIG_DEVICE, AUTOMAP_PARTITION],
                api.MAX_FILE_CHECKS + 1)
        self.assertNotEqual("", mount.error)
        self.assertFalse(mount.mapped)

    @mock.patch('os.path.exists')
    @mock.patch('nova.privsep.fs.create_device_maps',
                return_value=(None, None))
    def test_map_dev_error_then_pass(self, mock_create_maps, mock_exists):
        mock_exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: False,
            MAP_PARTITION: [False, False, True]})
        mount = self._test_map_dev(PARTITION)
        self._check_calls(mock_exists, [ORIG_DEVICE, AUTOMAP_PARTITION], 3)
        self.assertEqual("", mount.error)
        self.assertTrue(mount.mapped)

    @mock.patch('os.path.exists')
    def test_map_dev_automap(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: True})
        mount = self._test_map_dev(PARTITION)
        self._check_calls(exists,
            [ORIG_DEVICE, AUTOMAP_PARTITION, AUTOMAP_PARTITION])
        self.assertEqual(AUTOMAP_PARTITION, mount.mapped_device)
        self.assertTrue(mount.automapped)
        self.assertTrue(mount.mapped)

    @mock.patch('os.path.exists')
    def test_map_dev_else(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: True})
        mount = self._test_map_dev(None)
        self._check_calls(exists, [ORIG_DEVICE])
        self.assertEqual(ORIG_DEVICE, mount.mapped_device)
        self.assertFalse(mount.automapped)
        self.assertTrue(mount.mapped)

    def test_instance_for_format_raw(self):
        image = imgmodel.LocalFileImage("/some/file.raw",
                                        imgmodel.FORMAT_RAW)
        mount_dir = '/mount/dir'
        partition = -1
        inst = api.Mount.instance_for_format(image, mount_dir, partition)
        self.assertIsInstance(inst, loop.LoopMount)

    def test_instance_for_format_qcow2(self):
        image = imgmodel.LocalFileImage("/some/file.qcows",
                                        imgmodel.FORMAT_QCOW2)
        mount_dir = '/mount/dir'
        partition = -1
        inst = api.Mount.instance_for_format(image, mount_dir, partition)
        self.assertIsInstance(inst, nbd.NbdMount)

    def test_instance_for_format_block(self):
        image = imgmodel.LocalBlockImage(
            "/dev/mapper/instances--instance-0000001_disk",)
        mount_dir = '/mount/dir'
        partition = -1
        inst = api.Mount.instance_for_format(image, mount_dir, partition)
        self.assertIsInstance(inst, block.BlockMount)

    def test_instance_for_device_loop(self):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = -1
        device = '/dev/loop0'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, loop.LoopMount)

    def test_instance_for_device_loop_partition(self):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = 1
        device = '/dev/mapper/loop0p1'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, loop.LoopMount)

    def test_instance_for_device_nbd(self):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = -1
        device = '/dev/nbd0'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, nbd.NbdMount)

    def test_instance_for_device_nbd_partition(self):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = 1
        device = '/dev/mapper/nbd0p1'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, nbd.NbdMount)

    def test_instance_for_device_block(self):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = -1
        device = '/dev/mapper/instances--instance-0000001_disk'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, block.BlockMount)

    def test_instance_for_device_block_partiton(self,):
        image = mock.MagicMock()
        mount_dir = '/mount/dir'
        partition = 1
        device = '/dev/mapper/instances--instance-0000001_diskp1'
        inst = api.Mount.instance_for_device(image, mount_dir, partition,
                                               device)
        self.assertIsInstance(inst, block.BlockMount)
