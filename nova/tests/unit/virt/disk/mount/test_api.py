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

from nova import test
from nova.virt.disk.mount import api


PARTITION = 77
ORIG_DEVICE = "/dev/null"
AUTOMAP_PARTITION = "/dev/nullp77"
MAP_PARTITION = "/dev/mapper/nullp77"


class MountTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MountTestCase, self).setUp()

    def _test_map_dev(self, partition):
        mount = api.Mount(mock.sentinel.image, mock.sentinel.mount_dir)
        mount.device = ORIG_DEVICE
        mount.partition = partition
        mount.map_dev()
        return mount

    @mock.patch('nova.utils.trycmd')
    def _test_map_dev_with_trycmd(self, partition, trycmd):
        trycmd.return_value = [None, None]
        mount = self._test_map_dev(partition)
        self.assertEqual(1, trycmd.call_count)  # don't care about args
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

    def _check_calls(self, exists, filenames):
        self.assertEqual([mock.call(x) for x in filenames],
                         exists.call_args_list)

    @mock.patch('os.path.exists')
    def test_map_dev_partition_search(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True})
        mount = self._test_map_dev(-1)
        self._check_calls(exists, [ORIG_DEVICE])
        self.assertNotEqual("", mount.error)
        self.assertFalse(mount.mapped)

    @mock.patch('os.path.exists')
    def test_map_dev_good(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: False,
            MAP_PARTITION: [False, True]})
        mount = self._test_map_dev_with_trycmd(PARTITION)
        self._check_calls(exists,
            [ORIG_DEVICE, AUTOMAP_PARTITION, MAP_PARTITION, MAP_PARTITION])
        self.assertEqual("", mount.error)
        self.assertTrue(mount.mapped)

    @mock.patch('os.path.exists')
    def test_map_dev_error(self, exists):
        exists.side_effect = self._exists_effect({
            ORIG_DEVICE: True,
            AUTOMAP_PARTITION: False,
            MAP_PARTITION: False})
        mount = self._test_map_dev_with_trycmd(PARTITION)
        self._check_calls(exists,
            [ORIG_DEVICE, AUTOMAP_PARTITION, MAP_PARTITION, MAP_PARTITION])
        self.assertNotEqual("", mount.error)
        self.assertFalse(mount.mapped)

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
