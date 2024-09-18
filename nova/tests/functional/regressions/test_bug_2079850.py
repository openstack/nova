# SPDX-License-Identifier: Apache-2.0
import functools
import os
import shutil

import fixtures

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils.imageutils import format_inspector
from oslo_utils import units

import nova.conf

from nova import exception
from nova import objects
from nova import test
from nova.virt.libvirt import driver
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import utils as libvirt_utils


CONF = nova.conf.CONF


class TestBugBackingFilePartitionTables(test.NoDBTestCase):
    """Regression test for nova created backing files

    This test case is for a bug that was discovered where nova was creating
    backing files for swap and ephemeral disks. With the move to using the
    image format inspector form oslo.utils we gained the ability to inspect
    files for mbr and gpt partition tables.

    This is now a requirement for all backing files created by nova.
    """

    def setUp(self):
        super(TestBugBackingFilePartitionTables, self).setUp()
        self.base_dir = self.useFixture(
            fixtures.TempDir())
        if shutil.which("qemu-img") is None:
            self.skipTest("qemu-img not installed")
        if shutil.which("mkfs.vfat") is None:
            self.skipTest("mkfs.vfat not installed")

    def test_create_file(self):
        """Test that files created files have partition tables

        This test will create a file and then inspect it to ensure
        that it has a partition table so that it can be used as a
        backing file.
        """

        file_path = os.path.join(self.base_dir.path, 'test_file')
        libvirt_utils.create_image(file_path, 'raw', '64M')
        self.assertTrue(os.path.exists(file_path))
        # nova should ensure that any file we create has a partition table
        # inspector = format_inspector.GPTInspector.from_file(file_path)
        # self.assertIsNotNone(inspector)
        # inspector.safety_check()

        # however the libvirt_utils.create_image method does not create a
        # partition table so we should expect this to fail
        self.assertRaises(
            format_inspector.ImageFormatError,
            format_inspector.GPTInspector.from_file, file_path)

    def test_cache_file(self):
        """Test the qcow2 cache interaction for ephemeral disks

        This test will create a file via the image backend cache function
        and ensure that the backing file has a partition table
        """
        _create_ephemeral = driver.LibvirtDriver._create_ephemeral

        self.flags(use_cow_images=True)
        self.flags(instances_path=self.base_dir.path)
        self.flags(group='libvirt', images_type='qcow2')

        backend_image = imagebackend.Backend(CONF.use_cow_images).backend()
        instance = objects.Instance(uuid=uuids.instance)
        image = backend_image(instance, 'test_image')

        fn = functools.partial(
            _create_ephemeral, fs_label='ephemeral0',
            os_type=None, is_block_dev=False)
        # this need to be multiples of 1G
        size = 1 * units.Gi
        fname = "ephemeral_%s_%s" % (size, ".qcow")
        e = self.assertRaises(exception.InvalidDiskInfo,
            image.cache, fetch_func=fn, context=None, filename=fname,
            size=size, ephemeral_size=1)
        self.assertIn("Base image failed safety check", str(e))
