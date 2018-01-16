# Copyright 2011 Isaku Yamahata
# All Rights Reserved.
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

import io

import mock
import six

from nova import test
from nova.virt.disk import api as disk_api
from nova.virt import driver

PROC_MOUNTS_CONTENTS = """rootfs / rootfs rw 0 0
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
udev /dev devtmpfs rw,relatime,size=1013160k,nr_inodes=253290,mode=755 0 0
devpts /dev/pts devpts rw,nosuid,noexec,relatime,gid=5,mode=620 0 0
tmpfs /run tmpfs rw,nosuid,relatime,size=408904k,mode=755 0 0"""


class TestVirtDriver(test.NoDBTestCase):
    def test_block_device(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'num': 0,
                       'virtual_name': 'ephemeral0',
                       'device_name': '/dev/sdc1',
                       'size': 1}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        empty_block_device_info = {}

        self.assertEqual(
            driver.block_device_info_get_root_device(block_device_info),
            '/dev/sda')
        self.assertIsNone(
            driver.block_device_info_get_root_device(empty_block_device_info))
        self.assertIsNone(driver.block_device_info_get_root_device(None))

        self.assertEqual(
            driver.block_device_info_get_swap(block_device_info), swap)
        self.assertIsNone(driver.block_device_info_get_swap(
            empty_block_device_info)['device_name'])
        self.assertEqual(driver.block_device_info_get_swap(
            empty_block_device_info)['swap_size'], 0)
        self.assertIsNone(
            driver.block_device_info_get_swap({'swap': None})['device_name'])
        self.assertEqual(
            driver.block_device_info_get_swap({'swap': None})['swap_size'],
            0)
        self.assertIsNone(
            driver.block_device_info_get_swap(None)['device_name'])
        self.assertEqual(
            driver.block_device_info_get_swap(None)['swap_size'], 0)

        self.assertEqual(
            driver.block_device_info_get_ephemerals(block_device_info),
            ephemerals)
        self.assertEqual(
            driver.block_device_info_get_ephemerals(empty_block_device_info),
            [])
        self.assertEqual(
            driver.block_device_info_get_ephemerals(None),
            [])

    def test_swap_is_usable(self):
        self.assertFalse(driver.swap_is_usable(None))
        self.assertFalse(driver.swap_is_usable({'device_name': None}))
        self.assertFalse(driver.swap_is_usable({'device_name': '/dev/sdb',
                                                'swap_size': 0}))
        self.assertTrue(driver.swap_is_usable({'device_name': '/dev/sdb',
                                                'swap_size': 1}))


class FakeMount(object):
    def __init__(self, image, mount_dir, partition=None, device=None):
        self.image = image
        self.partition = partition
        self.mount_dir = mount_dir

        self.linked = self.mapped = self.mounted = False
        self.device = device

    def do_mount(self):
        self.linked = True
        self.mapped = True
        self.mounted = True
        self.device = '/dev/fake'
        return True

    def do_umount(self):
        self.linked = True
        self.mounted = False

    def do_teardown(self):
        self.linked = False
        self.mapped = False
        self.mounted = False
        self.device = None


class TestDiskImage(test.NoDBTestCase):
    def mock_proc_mounts(self, mock_open):
        response = io.StringIO(six.text_type(PROC_MOUNTS_CONTENTS))
        mock_open.return_value = response

    @mock.patch.object(six.moves.builtins, 'open')
    def test_mount(self, mock_open):
        self.mock_proc_mounts(mock_open)
        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(image, mountdir, partition):
            return fakemount

        self.stub_out('nova.virt.disk.mount.api.Mount.instance_for_format',
                      staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')

    @mock.patch.object(six.moves.builtins, 'open')
    def test_umount(self, mock_open):
        self.mock_proc_mounts(mock_open)

        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(image, mountdir, partition):
            return fakemount

        self.stub_out('nova.virt.disk.mount.api.Mount.instance_for_format',
                      staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')
        diskimage.umount()
        self.assertIsNone(diskimage._mounter)

    @mock.patch.object(six.moves.builtins, 'open')
    def test_teardown(self, mock_open):
        self.mock_proc_mounts(mock_open)

        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(image, mountdir, partition):
            return fakemount

        self.stub_out('nova.virt.disk.mount.api.Mount.instance_for_format',
                      staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')
        diskimage.teardown()
        self.assertIsNone(diskimage._mounter)


class TestVirtDisk(test.NoDBTestCase):
    def setUp(self):
        super(TestVirtDisk, self).setUp()

        # TODO(mikal): this can probably be removed post privsep cleanup.
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stub_out('nova.utils.execute', fake_execute)

    def test_lxc_setup_container(self):
        image = '/tmp/fake-image'
        container_dir = '/mnt/fake_rootfs/'

        def proc_mounts(mount_point):
            return None

        def fake_instance_for_format(image, mountdir, partition):
            return FakeMount(image, mountdir, partition)

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('nova.virt.disk.api._DiskImage._device_for_path',
                      proc_mounts)
        self.stub_out('nova.virt.disk.mount.api.Mount.instance_for_format',
                      staticmethod(fake_instance_for_format))

        self.assertEqual(disk_api.setup_container(image, container_dir),
                         '/dev/fake')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.privsep.fs.loopremove')
    @mock.patch('nova.privsep.fs.umount')
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    @mock.patch('nova.privsep.fs.remove_device_maps')
    @mock.patch('nova.privsep.fs.blockdev_flush')
    def test_lxc_teardown_container(
            self, mock_blockdev_flush, mock_remove_maps, mock_nbd_disconnect,
            mock_umount, mock_loopremove, mock_exist):

        def proc_mounts(mount_point):
            mount_points = {
                '/mnt/loop/nopart': '/dev/loop0',
                '/mnt/loop/part': '/dev/mapper/loop0p1',
                '/mnt/nbd/nopart': '/dev/nbd15',
                '/mnt/nbd/part': '/dev/mapper/nbd15p1',
            }
            return mount_points[mount_point]

        self.stub_out('nova.virt.disk.api._DiskImage._device_for_path',
                      proc_mounts)

        disk_api.teardown_container('/mnt/loop/nopart')
        mock_loopremove.assert_has_calls([mock.call('/dev/loop0')])
        mock_loopremove.reset_mock()
        mock_umount.assert_has_calls([mock.call('/dev/loop0')])
        mock_umount.reset_mock()

        disk_api.teardown_container('/mnt/loop/part')
        mock_loopremove.assert_has_calls([mock.call('/dev/loop0')])
        mock_loopremove.reset_mock()
        mock_umount.assert_has_calls([mock.call('/dev/mapper/loop0p1')])
        mock_umount.reset_mock()
        mock_remove_maps.assert_has_calls([mock.call('/dev/loop0')])
        mock_remove_maps.reset_mock()

        disk_api.teardown_container('/mnt/nbd/nopart')
        mock_nbd_disconnect.assert_has_calls([mock.call('/dev/nbd15')])
        mock_umount.assert_has_calls([mock.call('/dev/nbd15')])
        mock_blockdev_flush.assert_has_calls([mock.call('/dev/nbd15')])
        mock_nbd_disconnect.reset_mock()
        mock_umount.reset_mock()
        mock_blockdev_flush.reset_mock()

        disk_api.teardown_container('/mnt/nbd/part')
        mock_nbd_disconnect.assert_has_calls([mock.call('/dev/nbd15')])
        mock_umount.assert_has_calls([mock.call('/dev/mapper/nbd15p1')])
        mock_blockdev_flush.assert_has_calls([mock.call('/dev/nbd15')])
        mock_nbd_disconnect.reset_mock()
        mock_umount.reset_mock()
        mock_remove_maps.assert_has_calls([mock.call('/dev/nbd15')])
        mock_remove_maps.reset_mock()
        mock_blockdev_flush.reset_mock()

        # NOTE(thomasem): Not adding any commands in this case, because we're
        # not expecting an additional umount for LocalBlockImages. This is to
        # assert that no additional commands are run in this case.
        disk_api.teardown_container('/dev/volume-group/uuid_disk')
        mock_umount.assert_not_called()

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.virt.disk.api._DiskImage._device_for_path',
                return_value=None)
    @mock.patch('nova.privsep.fs.loopremove')
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    def test_lxc_teardown_container_with_namespace_cleaned(
            self, mock_nbd_disconnect, mock_loopremove, mock_device_for_path,
            mock_exists):

        disk_api.teardown_container('/mnt/loop/nopart', '/dev/loop0')
        mock_loopremove.assert_has_calls([mock.call('/dev/loop0')])
        mock_loopremove.reset_mock()

        disk_api.teardown_container('/mnt/loop/part', '/dev/loop0')
        mock_loopremove.assert_has_calls([mock.call('/dev/loop0')])
        mock_loopremove.reset_mock()

        disk_api.teardown_container('/mnt/nbd/nopart', '/dev/nbd15')
        mock_nbd_disconnect.assert_has_calls([mock.call('/dev/nbd15')])
        mock_nbd_disconnect.reset_mock()

        disk_api.teardown_container('/mnt/nbd/part', '/dev/nbd15')
        mock_nbd_disconnect.assert_has_calls([mock.call('/dev/nbd15')])
        mock_nbd_disconnect.reset_mock()
