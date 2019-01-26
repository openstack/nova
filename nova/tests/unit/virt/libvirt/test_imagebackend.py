# Copyright 2012 Grid Dynamics
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

import base64
import errno
import os
import shutil
import tempfile

from castellan import key_manager
import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture
from oslo_utils import imageutils
from oslo_utils import units
from oslo_utils import uuidutils

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_processutils
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova import utils
from nova.virt.image import model as imgmodel
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt.storage import rbd_utils

CONF = nova.conf.CONF


class FakeSecret(object):

    def value(self):
        return base64.b64decode("MTIzNDU2Cg==")


class FakeConn(object):

    def secretLookupByUUIDString(self, uuid):
        return FakeSecret()


class _ImageTestCase(object):

    def mock_create_image(self, image):
        def create_image(fn, base, size, *args, **kwargs):
            fn(target=base, *args, **kwargs)
        image.create_image = create_image

    def setUp(self):
        super(_ImageTestCase, self).setUp()
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.INSTANCES_PATH = tempfile.mkdtemp(suffix='instances')
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')
        self.flags(instances_path=self.INSTANCES_PATH)
        self.INSTANCE = objects.Instance(id=1, uuid=uuidutils.generate_uuid())
        self.DISK_INFO_PATH = os.path.join(self.INSTANCES_PATH,
                                           self.INSTANCE['uuid'], 'disk.info')
        self.NAME = 'fake.vm'
        self.TEMPLATE = 'template'
        self.CONTEXT = context.get_admin_context()

        self.PATH = os.path.join(
            fake_libvirt_utils.get_instance_path(self.INSTANCE), self.NAME)

        # TODO(mikal): rename template_dir to base_dir and template_path
        # to cached_image_path. This will be less confusing.
        self.TEMPLATE_DIR = os.path.join(CONF.instances_path, '_base')
        self.TEMPLATE_PATH = os.path.join(self.TEMPLATE_DIR, 'template')

        # Ensure can_fallocate is not initialised on the class
        if hasattr(self.image_class, 'can_fallocate'):
            del self.image_class.can_fallocate

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.libvirt_utils',
            fake_libvirt_utils))

        # This will be used to mock some decorations like utils.synchronize
        def _fake_deco(func):
            return func
        self._fake_deco = _fake_deco

    def tearDown(self):
        super(_ImageTestCase, self).tearDown()
        shutil.rmtree(self.INSTANCES_PATH)

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('os.access', lambda p, w: True)
        with mock.patch.object(image, 'get_disk_size', return_value=self.SIZE):
            # Call twice to verify testing fallocate is only called once.
            image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)
            image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

            self.assertEqual(fake_processutils.fake_execute_get_log(),
                ['fallocate -l 1 %s.fallocate_test' % self.PATH,
                 'fallocate -n -l %s %s' % (self.SIZE, self.PATH),
                 'fallocate -n -l %s %s' % (self.SIZE, self.PATH)])

    def test_prealloc_image_without_write_access(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        with test.nested(
            mock.patch.object(image, 'exists', lambda: True),
            mock.patch.object(image, '_can_fallocate', lambda: True),
            mock.patch.object(image, 'get_disk_size', lambda _: self.SIZE)
        ) as (mock_exists, mock_can, mock_get):
            self.stub_out('os.path.exists', lambda _: True)
            self.stub_out('os.access', lambda p, w: False)

            # Testing fallocate is only called when user has write access.
            image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

            self.assertEqual(fake_processutils.fake_execute_get_log(), [])

    def test_libvirt_fs_info(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        fs = image.libvirt_fs_info("/mnt")
        # check that exception hasn't been raised and the method
        # returned correct object
        self.assertIsInstance(fs, vconfig.LibvirtConfigGuestFilesys)
        self.assertEqual(fs.target_dir, "/mnt")
        if image.is_block_dev:
            self.assertEqual(fs.source_type, "block")
            self.assertEqual(fs.source_dev, image.path)
        else:
            self.assertEqual(fs.source_type, "file")
            self.assertEqual(fs.source_file, image.path)

    def test_libvirt_info(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        extra_specs = {
            'quota:disk_read_bytes_sec': 10 * units.Mi,
            'quota:disk_read_iops_sec': 1 * units.Ki,
            'quota:disk_write_bytes_sec': 20 * units.Mi,
            'quota:disk_write_iops_sec': 2 * units.Ki,
            'quota:disk_total_bytes_sec': 30 * units.Mi,
            'quota:disk_total_iops_sec': 3 * units.Ki,
        }

        disk = image.libvirt_info(disk_bus="virtio",
                                  disk_dev="/dev/vda",
                                  device_type="cdrom",
                                  cache_mode="none",
                                  extra_specs=extra_specs,
                                  hypervisor_version=4004001,
                                  boot_order="1")

        self.assertIsInstance(disk, vconfig.LibvirtConfigGuestDisk)
        self.assertEqual("/dev/vda", disk.target_dev)
        self.assertEqual("virtio", disk.target_bus)
        self.assertEqual("none", disk.driver_cache)
        self.assertEqual("cdrom", disk.source_device)
        self.assertEqual("1", disk.boot_order)

        self.assertEqual(10 * units.Mi, disk.disk_read_bytes_sec)
        self.assertEqual(1 * units.Ki, disk.disk_read_iops_sec)
        self.assertEqual(20 * units.Mi, disk.disk_write_bytes_sec)
        self.assertEqual(2 * units.Ki, disk.disk_write_iops_sec)
        self.assertEqual(30 * units.Mi, disk.disk_total_bytes_sec)
        self.assertEqual(3 * units.Ki, disk.disk_total_iops_sec)

    @mock.patch('nova.virt.disk.api.get_disk_size')
    def test_get_disk_size(self, get_disk_size):
        get_disk_size.return_value = 2361393152

        image = self.image_class(self.INSTANCE, self.NAME)
        self.assertEqual(2361393152, image.get_disk_size(image.path))
        get_disk_size.assert_called_once_with(image.path)


class FlatTestCase(_ImageTestCase, test.NoDBTestCase):

    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Flat
        super(FlatTestCase, self).setUp()

    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    @mock.patch.object(os.path, 'exists')
    def test_cache(self, mock_exists, mock_ensure):
        self.stub_out('nova.virt.libvirt.imagebackend.Flat.correct_format',
                       lambda _: None)
        mock_exists.side_effect = [False, False, False]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH), mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        fn(target=self.TEMPLATE_PATH)
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_ensure.assert_called_once_with(self.TEMPLATE_DIR)
        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_image_exists(self, mock_exists):
        self.stub_out('nova.virt.libvirt.imagebackend.Flat.correct_format',
                      lambda _: None)
        mock_exists.side_effect = [True, True, True]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH), mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.cache(None, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_base_dir_exists(self, mock_exists):
        self.stub_out('nova.virt.libvirt.imagebackend.Flat.correct_format',
                      lambda _: None)
        mock_exists.side_effect = [True, False, False]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH), mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        fn(target=self.TEMPLATE_PATH)
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_template_exists(self, mock_exists):
        self.stub_out('nova.virt.libvirt.imagebackend.Flat.correct_format',
                      lambda _: None)
        mock_exists.side_effect = [True, False, True]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH), mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(None, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch('os.path.exists')
    def test_cache_generating_resize(self, mock_path_exists):
        # Test for bug 1608934

        # The Flat backend doesn't write to the image cache when creating a
        # non-image backend. Test that we don't try to get the disk size of
        # a non-existent backend.

        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)

        # Lets assume the base image cache directory already exists
        existing = set([base_dir])

        def fake_exists(path):
            # Return True only for files previously created during
            # execution. This allows us to test that we're not calling
            # get_disk_size() on something which hasn't been previously
            # created.
            return path in existing

        def fake_get_disk_size(path):
            # get_disk_size will explode if called on a path which doesn't
            # exist. Specific exception not important for this test.
            if path not in existing:
                raise AssertionError

            # Not important, won't actually be called by patched code.
            return 2 * units.Gi

        def fake_template(target=None, **kwargs):
            # The template function we pass to cache. Calling this will
            # cause target to be created.
            existing.add(target)

        mock_path_exists.side_effect = fake_exists

        image = self.image_class(self.INSTANCE, self.NAME)

        # We're not testing preallocation
        image.preallocate = False

        with test.nested(
            mock.patch.object(image, 'exists'),
            mock.patch.object(image, 'correct_format'),
            mock.patch.object(image, 'get_disk_size'),
            mock.patch.object(image, 'resize_image')
        ) as (
            mock_disk_exists, mock_correct_format, mock_get_disk_size,
            mock_resize_image
        ):
            # Assume the disk doesn't already exist
            mock_disk_exists.return_value = False

            # This won't actually be executed since change I46b5658e,
            # but this is how the unpatched code will fail. We include this
            # here as a belt-and-braces sentinel.
            mock_get_disk_size.side_effect = fake_get_disk_size

            # Try to create a 2G image
            image.cache(fake_template, 'fake_cache_name', 2 * units.Gi)

            # The real assertion is that the above call to cache() didn't
            # raise AssertionError which, if we get here, it clearly didn't.
            self.assertFalse(image.resize_image.called)

    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(fake_libvirt_utils, 'copy_image')
    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch('nova.privsep.path.utime')
    def test_create_image(self, mock_utime, mock_sync, mock_copy, mock_extend):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None, image_id=None)

        mock_copy.assert_called_once_with(self.TEMPLATE_PATH, self.PATH)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH, image_id=None)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_extend.called)
        mock_utime.assert_called()

    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(fake_libvirt_utils, 'copy_image')
    @mock.patch.object(imagebackend.utils, 'synchronized')
    def test_create_image_generated(self, mock_sync, mock_copy, mock_extend):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, None)

        fn.assert_called_once_with(target=self.PATH)
        self.assertFalse(mock_copy.called)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_extend.called)

    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(fake_libvirt_utils, 'copy_image')
    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(images, 'qemu_img_info',
                       return_value=imageutils.QemuImgInfo())
    @mock.patch('nova.privsep.path.utime')
    def test_create_image_extend(self, mock_utime, mock_qemu, mock_sync,
                                 mock_copy, mock_extend):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        mock_qemu.return_value.virtual_size = 1024
        fn(target=self.TEMPLATE_PATH, image_id=None)
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH,
                           self.SIZE, image_id=None)

        mock_copy.assert_called_once_with(self.TEMPLATE_PATH, self.PATH)
        self.assertTrue(mock_sync.called)
        mock_extend.assert_called_once_with(
            imgmodel.LocalFileImage(self.PATH, imgmodel.FORMAT_RAW),
            self.SIZE)
        mock_qemu.assert_called_once_with(self.TEMPLATE_PATH)
        mock_utime.assert_called()

    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(imagebackend.images, 'qemu_img_info')
    def test_correct_format(self, mock_qemu, mock_exist):
        mock_exist.side_effect = [True, False, True]
        info = mock.MagicMock()
        info.file_format = 'foo'
        mock_qemu.return_value = info

        image = self.image_class(self.INSTANCE, self.NAME, path=self.PATH)

        self.assertEqual(image.driver_format, 'foo')
        mock_qemu.assert_called_once_with(self.PATH)
        mock_exist.assert_has_calls([mock.call(self.PATH),
                                     mock.call(self.DISK_INFO_PATH),
                                     mock.call(CONF.instances_path)])

    @mock.patch.object(images, 'qemu_img_info',
                       side_effect=exception.InvalidDiskInfo(
                           reason='invalid path'))
    def test_resolve_driver_format(self, fake_qemu_img_info):
        image = self.image_class(self.INSTANCE, self.NAME)
        driver_format = image.resolve_driver_format()
        self.assertEqual(driver_format, 'raw')

    def test_get_model(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        model = image.get_model(FakeConn())
        self.assertEqual(imgmodel.LocalFileImage(self.PATH,
                                                 imgmodel.FORMAT_RAW),
                         model)


class Qcow2TestCase(_ImageTestCase, test.NoDBTestCase):
    SIZE = units.Gi

    def setUp(self):
        self.image_class = imagebackend.Qcow2
        super(Qcow2TestCase, self).setUp()
        self.QCOW2_BASE = (self.TEMPLATE_PATH +
                           '_%d' % (self.SIZE / units.Gi))

    @mock.patch.object(os.path, 'exists')
    def test_cache(self, mock_exists):
        mock_exists.side_effect = [False, True, False, True, False, False]
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(CONF.instances_path),
                       mock.call(self.TEMPLATE_DIR),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]

        image.cache(fn, self.TEMPLATE)

        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_image_exists(self, mock_exists):
        mock_exists.side_effect = [False, True, True, True, True]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.cache(None, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_base_dir_exists(self, mock_exists):
        mock_exists.side_effect = [False, True, True, False, False]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_template_exists(self, mock_exists):
        mock_exists.side_effect = [False, True, True, False, True]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(None, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'create_cow_image')
    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch('nova.privsep.path.utime')
    def test_create_image(self, mock_utime, mock_extend, mock_create,
                          mock_sync):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, None)

        mock_create.assert_called_once_with(self.TEMPLATE_PATH, self.PATH)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_extend.called)
        mock_utime.assert_called()

    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'create_cow_image')
    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(os.path, 'exists', side_effect=[])
    @mock.patch.object(imagebackend.Image, 'verify_base_size')
    @mock.patch('nova.privsep.path.utime')
    def test_create_image_with_size(self, mock_utime, mock_verify, mock_exist,
                                    mock_extend, mock_create, mock_sync):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        mock_exist.side_effect = [False, True, False, False, False]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_PATH),
                       mock.call(self.PATH),
                       mock.call(self.PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        mock_verify.assert_called_once_with(self.TEMPLATE_PATH, self.SIZE)
        mock_create.assert_called_once_with(self.TEMPLATE_PATH, self.PATH)
        mock_extend.assert_called_once_with(
            imgmodel.LocalFileImage(self.PATH, imgmodel.FORMAT_QCOW2),
            self.SIZE)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_exist.assert_has_calls(exist_calls)
        self.assertTrue(mock_sync.called)
        mock_utime.assert_called()

    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'create_cow_image')
    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(os.path, 'exists', side_effect=[])
    @mock.patch.object(imagebackend.Qcow2, 'get_disk_size')
    @mock.patch('nova.privsep.path.utime')
    def test_create_image_too_small(self, mock_utime, mock_get, mock_exist,
                                    mock_extend, mock_create, mock_sync):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        mock_get.return_value = self.SIZE
        fn = mock.MagicMock()
        mock_exist.side_effect = [False, True, True]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(exception.FlavorDiskSmallerThanImage,
                          image.create_image, fn, self.TEMPLATE_PATH, 1)
        mock_get.assert_called_once_with(self.TEMPLATE_PATH)
        mock_exist.assert_has_calls(exist_calls)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_create.called)
        self.assertFalse(mock_extend.called)

    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'create_cow_image')
    @mock.patch.object(fake_libvirt_utils, 'get_disk_backing_file')
    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(os.path, 'exists', side_effect=[])
    @mock.patch.object(imagebackend.Image, 'verify_base_size')
    @mock.patch.object(fake_libvirt_utils, 'copy_image')
    @mock.patch('nova.privsep.path.utime')
    def test_generate_resized_backing_files(self, mock_utime, mock_copy,
                                            mock_verify, mock_exist,
                                            mock_extend, mock_get,
                                            mock_create, mock_sync):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        mock_get.return_value = self.QCOW2_BASE
        fn = mock.MagicMock()
        mock_exist.side_effect = [False, True, False, True, False, True]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(CONF.instances_path),
                       mock.call(self.TEMPLATE_PATH),
                       mock.call(self.PATH),
                       mock.call(self.QCOW2_BASE),
                       mock.call(self.PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        mock_get.assert_called_once_with(self.PATH)
        mock_verify.assert_called_once_with(self.TEMPLATE_PATH, self.SIZE)
        mock_copy.assert_called_once_with(self.TEMPLATE_PATH,
                                          self.QCOW2_BASE)
        mock_extend.assert_called_once_with(
            imgmodel.LocalFileImage(self.QCOW2_BASE,
                                    imgmodel.FORMAT_QCOW2), self.SIZE)
        mock_exist.assert_has_calls(exist_calls)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_create.called)
        mock_utime.assert_called()

    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'create_cow_image')
    @mock.patch.object(fake_libvirt_utils, 'get_disk_backing_file')
    @mock.patch.object(imagebackend.disk, 'extend')
    @mock.patch.object(os.path, 'exists', side_effect=[])
    @mock.patch.object(imagebackend.Image, 'verify_base_size')
    @mock.patch('nova.privsep.path.utime')
    def test_qcow2_exists_and_has_no_backing_file(self, mock_utime,
                                                  mock_verify, mock_exist,
                                                  mock_extend, mock_get,
                                                  mock_create, mock_sync):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        mock_get.return_value = None
        fn = mock.MagicMock()
        mock_exist.side_effect = [False, True, False, True, True]
        exist_calls = [mock.call(self.DISK_INFO_PATH),
                       mock.call(self.INSTANCES_PATH),
                       mock.call(self.TEMPLATE_PATH),
                       mock.call(self.PATH),
                       mock.call(self.PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        mock_get.assert_called_once_with(self.PATH)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_verify.assert_called_once_with(self.TEMPLATE_PATH, self.SIZE)
        mock_exist.assert_has_calls(exist_calls)
        self.assertTrue(mock_sync.called)
        self.assertFalse(mock_create.called)
        self.assertFalse(mock_extend.called)

    def test_resolve_driver_format(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        driver_format = image.resolve_driver_format()
        self.assertEqual(driver_format, 'qcow2')

    def test_get_model(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        model = image.get_model(FakeConn())
        self.assertEqual(imgmodel.LocalFileImage(self.PATH,
                                                 imgmodel.FORMAT_QCOW2),
                        model)


class LvmTestCase(_ImageTestCase, test.NoDBTestCase):
    VG = 'FakeVG'
    TEMPLATE_SIZE = 512
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Lvm
        super(LvmTestCase, self).setUp()
        self.flags(images_volume_group=self.VG, group='libvirt')
        self.flags(enabled=False, group='ephemeral_storage_encryption')
        self.INSTANCE['ephemeral_key_uuid'] = None
        self.LV = '%s_%s' % (self.INSTANCE['uuid'], self.NAME)
        self.PATH = os.path.join('/dev', self.VG, self.LV)

    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    @mock.patch.object(imagebackend.lvm, 'create_volume')
    @mock.patch.object(imagebackend.disk, 'get_disk_size',
                       return_value=TEMPLATE_SIZE)
    @mock.patch('nova.privsep.qemu.convert_image')
    def _create_image(self, sparse, mock_convert_image, mock_get, mock_create,
                      mock_ignored):
        fn = mock.MagicMock()

        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, None)

        mock_create.assert_called_once_with(self.VG, self.LV,
                                            self.TEMPLATE_SIZE,
                                            sparse=sparse)

        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_get.assert_called_once_with(self.TEMPLATE_PATH)
        path = '/dev/%s/%s_%s' % (self.VG, self.INSTANCE.uuid, self.NAME)
        mock_convert_image.assert_called_once_with(
            self.TEMPLATE_PATH, path, None, 'raw', CONF.instances_path)

    @mock.patch.object(imagebackend.lvm, 'create_volume')
    def _create_image_generated(self, sparse, mock_create):
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH,
                self.SIZE, ephemeral_size=None)

        mock_create.assert_called_once_with(self.VG, self.LV,
                                            self.SIZE, sparse=sparse)
        fn.assert_called_once_with(target=self.PATH, ephemeral_size=None)

    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    @mock.patch.object(imagebackend.disk, 'resize2fs')
    @mock.patch.object(imagebackend.lvm, 'create_volume')
    @mock.patch.object(imagebackend.disk, 'get_disk_size',
                       return_value=TEMPLATE_SIZE)
    @mock.patch('nova.privsep.qemu.convert_image')
    def _create_image_resize(self, sparse, mock_convert_image, mock_get,
                             mock_create, mock_resize, mock_ignored):
        fn = mock.MagicMock()
        fn(target=self.TEMPLATE_PATH)
        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        mock_create.assert_called_once_with(self.VG, self.LV,
                                            self.SIZE, sparse=sparse)
        mock_get.assert_called_once_with(self.TEMPLATE_PATH)
        mock_convert_image.assert_called_once_with(
            self.TEMPLATE_PATH, self.PATH, None, 'raw',
            CONF.instances_path)
        mock_resize.assert_called_once_with(self.PATH, run_as_root=True)

    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    @mock.patch.object(os.path, 'exists')
    def test_cache(self, mock_exists, mock_ensure):
        mock_exists.side_effect = [False, False, False]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_ensure.assert_called_once_with(self.TEMPLATE_DIR)
        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(os.path, 'exists')
    def test_cache_image_exists(self, mock_exists):
        mock_exists.side_effect = [True, True, True]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        image = self.image_class(self.INSTANCE, self.NAME)

        image.cache(None, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)

    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    @mock.patch.object(os.path, 'exists', side_effect=[True, False, False])
    def test_cache_base_dir_exists(self, mock_exists, mock_ensure):
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH),
                       mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_exists.assert_has_calls(exist_calls)
        mock_ensure.assert_not_called()

    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('nova.utils.synchronized', autospec=True)
    @mock.patch.object(imagebackend, 'lvm', autospec=True)
    @mock.patch.object(imagebackend.fileutils, 'ensure_tree', autospec=True)
    def test_cache_ephemeral(self, mock_ensure, mock_lvm, mock_synchronized,
                             mock_exists):
        # Ignores its arguments and returns the wrapped function unmodified
        def fake_synchronized(*args, **kwargs):
            def outer(fn):
                def wrapper(*wargs, **wkwargs):
                    fn(*wargs, **wkwargs)
                return wrapper

            return outer

        mock_synchronized.side_effect = fake_synchronized

        # Fake exists returns true for paths which have been added to the
        # exists set
        exists = set()

        def fake_exists(path):
            return path in exists

        mock_exists.side_effect = fake_exists

        # Fake create_volume causes exists to return true for the volume
        def fake_create_volume(vg, lv, size, sparse=False):
            exists.add(os.path.join('/dev', vg, lv))

        mock_lvm.create_volume.side_effect = fake_create_volume

        # Assert that when we call cache() for an ephemeral disk with the
        # Lvm backend, we call fetch_func with a target of the Lvm disk
        size_gb = 1
        size = size_gb * units.Gi

        fetch_func = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        image.cache(fetch_func, self.TEMPLATE,
                    ephemeral_size=size_gb, size=size)

        mock_ensure.assert_called_once_with(self.TEMPLATE_DIR)
        mock_lvm.create_volume.assert_called_once_with(self.VG, self.LV, size,
                                                       sparse=False)
        fetch_func.assert_called_once_with(target=self.PATH,
                                           ephemeral_size=size_gb)

        mock_synchronized.assert_called()

    def test_create_image(self):
        self._create_image(False)

    def test_create_image_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image(True)

    def test_create_image_generated(self):
        self._create_image_generated(False)

    def test_create_image_generated_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image_generated(True)

    def test_create_image_resize(self):
        self._create_image_resize(False)

    def test_create_image_resize_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image_resize(True)

    @mock.patch.object(imagebackend.lvm, 'create_volume',
                       side_effect=RuntimeError)
    @mock.patch.object(imagebackend.disk, 'get_disk_size',
                       return_value=TEMPLATE_SIZE)
    @mock.patch.object(imagebackend.lvm, 'remove_volumes')
    def test_create_image_negative(self, mock_remove, mock_get, mock_create):
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(RuntimeError, image.create_image, fn,
                          self.TEMPLATE_PATH, self.SIZE)
        mock_create.assert_called_once_with(self.VG, self.LV,
                                            self.SIZE, sparse=False)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_get.assert_called_once_with(self.TEMPLATE_PATH)
        mock_remove.assert_called_once_with([self.PATH])

    @mock.patch.object(imagebackend.lvm, 'create_volume')
    @mock.patch.object(imagebackend.lvm, 'remove_volumes')
    def test_create_image_generated_negative(self, mock_remove, mock_create):
        fn = mock.MagicMock()
        fn.side_effect = RuntimeError
        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(RuntimeError, image.create_image, fn,
                          self.TEMPLATE_PATH, self.SIZE,
                          ephemeral_size=None)
        mock_create.assert_called_once_with(self.VG, self.LV, self.SIZE,
                                            sparse=False)
        fn.assert_called_once_with(target=self.PATH, ephemeral_size=None)
        mock_remove.assert_called_once_with([self.PATH])

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Lvm.exists',
                      lambda *a, **kw: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Lvm.get_disk_size',
                      lambda *a, **kw: self.SIZE)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])


class EncryptedLvmTestCase(_ImageTestCase, test.NoDBTestCase):
    VG = 'FakeVG'
    TEMPLATE_SIZE = 512
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Lvm
        super(EncryptedLvmTestCase, self).setUp()
        self.flags(enabled=True, group='ephemeral_storage_encryption')
        self.flags(cipher='aes-xts-plain64',
                   group='ephemeral_storage_encryption')
        self.flags(key_size=512, group='ephemeral_storage_encryption')
        self.flags(fixed_key='00000000000000000000000000000000'
                             '00000000000000000000000000000000',
                   group='key_manager')
        self.flags(images_volume_group=self.VG, group='libvirt')
        self.LV = '%s_%s' % (self.INSTANCE['uuid'], self.NAME)
        self.LV_PATH = os.path.join('/dev', self.VG, self.LV)
        self.PATH = os.path.join('/dev/mapper',
            imagebackend.dmcrypt.volume_name(self.LV))
        self.key_manager = key_manager.API()
        self.INSTANCE['ephemeral_key_uuid'] =\
            self.key_manager.create_key(self.CONTEXT, 'AES', 256)
        self.KEY = self.key_manager.get(self.CONTEXT,
            self.INSTANCE['ephemeral_key_uuid']).get_encoded()

        self.lvm = imagebackend.lvm
        self.disk = imagebackend.disk
        self.utils = imagebackend.utils
        self.libvirt_utils = imagebackend.libvirt_utils
        self.dmcrypt = imagebackend.dmcrypt

    def _create_image(self, sparse):
        with test.nested(
                mock.patch('nova.privsep.utils.supports_direct_io',
                           return_value=True),
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch('nova.privsep.qemu.convert_image')):
            fn = mock.Mock()

            image = self.image_class(self.INSTANCE, self.NAME)
            image.create_image(fn, self.TEMPLATE_PATH, self.TEMPLATE_SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(context=self.CONTEXT,
                target=self.TEMPLATE_PATH)
            self.lvm.create_volume.assert_called_with(self.VG,
                self.LV,
                self.TEMPLATE_SIZE,
                sparse=sparse)
            self.dmcrypt.create_volume.assert_called_with(
                self.PATH.rpartition('/')[2],
                self.LV_PATH,
                CONF.ephemeral_storage_encryption.cipher,
                CONF.ephemeral_storage_encryption.key_size,
                self.KEY)
            nova.privsep.qemu.convert_image.assert_called_with(
                self.TEMPLATE_PATH, self.PATH, None, 'raw',
                CONF.instances_path)

    def _create_image_generated(self, sparse):
        with test.nested(
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch('nova.privsep.qemu.convert_image')):
            fn = mock.Mock()

            image = self.image_class(self.INSTANCE, self.NAME)
            image.create_image(fn, self.TEMPLATE_PATH,
                self.SIZE,
                ephemeral_size=None,
                context=self.CONTEXT)

            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=sparse)
            self.dmcrypt.create_volume.assert_called_with(
                self.PATH.rpartition('/')[2],
                self.LV_PATH,
                CONF.ephemeral_storage_encryption.cipher,
                CONF.ephemeral_storage_encryption.key_size,
                self.KEY)
            fn.assert_called_with(target=self.PATH,
                ephemeral_size=None, context=self.CONTEXT)

    def _create_image_resize(self, sparse):
        with test.nested(
                mock.patch('nova.privsep.utils.supports_direct_io',
                           return_value=True),
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch('nova.privsep.qemu.convert_image')):
            fn = mock.Mock()

            image = self.image_class(self.INSTANCE, self.NAME)
            image.create_image(fn, self.TEMPLATE_PATH, self.SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(context=self.CONTEXT,
                                  target=self.TEMPLATE_PATH)
            self.disk.get_disk_size.assert_called_with(self.TEMPLATE_PATH)
            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=sparse)
            self.dmcrypt.create_volume.assert_called_with(
                 self.PATH.rpartition('/')[2],
                 self.LV_PATH,
                 CONF.ephemeral_storage_encryption.cipher,
                 CONF.ephemeral_storage_encryption.key_size,
                 self.KEY)
            nova.privsep.qemu.convert_image.assert_called_with(
                self.TEMPLATE_PATH, self.PATH, None, 'raw',
                CONF.instances_path)
            self.disk.resize2fs.assert_called_with(self.PATH, run_as_root=True)

    def test_create_image(self):
        self._create_image(False)

    def test_create_image_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image(True)

    def test_create_image_generated(self):
        self._create_image_generated(False)

    def test_create_image_generated_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image_generated(True)

    def test_create_image_resize(self):
        self._create_image_resize(False)

    def test_create_image_resize_sparsed(self):
        self.flags(sparse_logical_volumes=True, group='libvirt')
        self._create_image_resize(True)

    def test_create_image_negative(self):
        with test.nested(
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch.object(self.utils, 'execute', mock.Mock())):
            fn = mock.Mock()
            self.lvm.create_volume.side_effect = RuntimeError()

            image = self.image_class(self.INSTANCE, self.NAME)
            self.assertRaises(
                RuntimeError,
                image.create_image,
                fn,
                self.TEMPLATE_PATH,
                self.SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(
                context=self.CONTEXT,
                target=self.TEMPLATE_PATH)
            self.disk.get_disk_size.assert_called_with(
                self.TEMPLATE_PATH)
            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=False)
            self.dmcrypt.delete_volume.assert_called_with(
                self.PATH.rpartition('/')[2])
            self.lvm.remove_volumes.assert_called_with([self.LV_PATH])

    def test_create_image_encrypt_negative(self):
        with test.nested(
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch.object(self.utils, 'execute', mock.Mock())):
            fn = mock.Mock()
            self.dmcrypt.create_volume.side_effect = RuntimeError()

            image = self.image_class(self.INSTANCE, self.NAME)
            self.assertRaises(
                RuntimeError,
                image.create_image,
                fn,
                self.TEMPLATE_PATH,
                self.SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(
                context=self.CONTEXT,
                target=self.TEMPLATE_PATH)
            self.disk.get_disk_size.assert_called_with(self.TEMPLATE_PATH)
            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=False)
            self.dmcrypt.create_volume.assert_called_with(
                self.dmcrypt.volume_name(self.LV),
                self.LV_PATH,
                CONF.ephemeral_storage_encryption.cipher,
                CONF.ephemeral_storage_encryption.key_size,
                self.KEY)
            self.dmcrypt.delete_volume.assert_called_with(
                self.PATH.rpartition('/')[2])
            self.lvm.remove_volumes.assert_called_with([self.LV_PATH])

    def test_create_image_generated_negative(self):
        with test.nested(
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch.object(self.utils, 'execute', mock.Mock())):
            fn = mock.Mock()
            fn.side_effect = RuntimeError()

            image = self.image_class(self.INSTANCE, self.NAME)
            self.assertRaises(RuntimeError,
                image.create_image,
                fn,
                self.TEMPLATE_PATH,
                self.SIZE,
                ephemeral_size=None,
                context=self.CONTEXT)

            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=False)
            self.dmcrypt.create_volume.assert_called_with(
                self.PATH.rpartition('/')[2],
                self.LV_PATH,
                CONF.ephemeral_storage_encryption.cipher,
                CONF.ephemeral_storage_encryption.key_size,
                self.KEY)
            fn.assert_called_with(
                target=self.PATH,
                ephemeral_size=None,
                context=self.CONTEXT)
            self.dmcrypt.delete_volume.assert_called_with(
                self.PATH.rpartition('/')[2])
            self.lvm.remove_volumes.assert_called_with([self.LV_PATH])

    def test_create_image_generated_encrypt_negative(self):
        with test.nested(
                mock.patch.object(self.lvm, 'create_volume', mock.Mock()),
                mock.patch.object(self.lvm, 'remove_volumes', mock.Mock()),
                mock.patch.object(self.disk, 'resize2fs', mock.Mock()),
                mock.patch.object(self.disk, 'get_disk_size',
                                  mock.Mock(return_value=self.TEMPLATE_SIZE)),
                mock.patch.object(self.dmcrypt, 'create_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'delete_volume', mock.Mock()),
                mock.patch.object(self.dmcrypt, 'list_volumes', mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'create_lvm_image',
                                  mock.Mock()),
                mock.patch.object(self.libvirt_utils, 'remove_logical_volumes',
                                  mock.Mock()),
                mock.patch.object(self.utils, 'execute', mock.Mock())):
            fn = mock.Mock()
            fn.side_effect = RuntimeError()

            image = self.image_class(self.INSTANCE, self.NAME)
            self.assertRaises(
                RuntimeError,
                image.create_image,
                fn,
                self.TEMPLATE_PATH,
                self.SIZE,
                ephemeral_size=None,
                context=self.CONTEXT)

            self.lvm.create_volume.assert_called_with(
                self.VG,
                self.LV,
                self.SIZE,
                sparse=False)
            self.dmcrypt.create_volume.assert_called_with(
                self.PATH.rpartition('/')[2],
                self.LV_PATH,
                CONF.ephemeral_storage_encryption.cipher,
                CONF.ephemeral_storage_encryption.key_size,
                self.KEY)
            self.dmcrypt.delete_volume.assert_called_with(
                self.PATH.rpartition('/')[2])
            self.lvm.remove_volumes.assert_called_with([self.LV_PATH])

    def test_prealloc_image(self):
        self.flags(preallocate_images='space')
        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Lvm.exists',
                      lambda *a, **kw: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Lvm.get_disk_size',
                      lambda *a, **kw: self.SIZE)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])

    def test_get_model(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        model = image.get_model(FakeConn())
        self.assertEqual(imgmodel.LocalBlockImage(self.PATH),
                         model)


class RbdTestCase(_ImageTestCase, test.NoDBTestCase):
    FSID = "FakeFsID"
    POOL = "FakePool"
    USER = "FakeUser"
    CONF = "FakeConf"
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Rbd
        super(RbdTestCase, self).setUp()
        self.flags(images_rbd_pool=self.POOL,
                   rbd_user=self.USER,
                   images_rbd_ceph_conf=self.CONF,
                   group='libvirt')
        self.libvirt_utils = imagebackend.libvirt_utils
        self.utils = imagebackend.utils

        # mock out the cephclients for avoiding ImportError exception
        rbd_utils.rbd = mock.Mock()
        rbd_utils.rados = mock.Mock()

    @mock.patch.object(os.path, 'exists', return_value=False)
    @mock.patch.object(imagebackend.Rbd, 'exists', return_value=False)
    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    def test_cache(self, mock_ensure, mock_img_exist, mock_os_exist):
        image = self.image_class(self.INSTANCE, self.NAME)
        fn = mock.MagicMock()
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_ensure.assert_called_once_with(self.TEMPLATE_DIR)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)
        mock_img_exist.assert_called_with()
        mock_os_exist.assert_has_calls([
            mock.call(self.TEMPLATE_DIR), mock.call(self.TEMPLATE_PATH)
        ])

    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(imagebackend.Rbd, 'exists')
    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    def test_cache_base_dir_exists(self, mock_ensure,
                                   mock_img_exist, mock_os_exist):
        mock_os_exist.side_effect = [True, False]
        mock_img_exist.return_value = False
        image = self.image_class(self.INSTANCE, self.NAME)
        fn = mock.MagicMock()
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_img_exist.assert_called_once_with()
        mock_os_exist.assert_has_calls([
            mock.call(self.TEMPLATE_DIR), mock.call(self.TEMPLATE_PATH)
        ])
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(imagebackend.Rbd, 'exists', return_value=True)
    def test_cache_image_exists(self, mock_img_exist, mock_os_exist):
        image = self.image_class(self.INSTANCE, self.NAME)

        image.cache(None, self.TEMPLATE)

        mock_img_exist.assert_called_once_with()
        mock_os_exist.assert_has_calls([
            mock.call(self.TEMPLATE_DIR), mock.call(self.TEMPLATE_PATH)
        ])

    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(imagebackend.Rbd, 'exists')
    def test_cache_template_exists(self, mock_img_exist, mock_os_exist):
        mock_os_exist.return_value = True
        mock_img_exist.return_value = False
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(None, self.TEMPLATE)

        mock_img_exist.assert_called_once_with()
        mock_os_exist.assert_has_calls([
            mock.call(self.TEMPLATE_DIR), mock.call(self.TEMPLATE_PATH)
        ])

    @mock.patch.object(imagebackend.Rbd, 'exists')
    def test_create_image(self, mock_exists):
        fn = mock.MagicMock()

        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)

        image = self.image_class(self.INSTANCE, self.NAME)
        mock_exists.return_value = False

        image.create_image(fn, self.TEMPLATE_PATH, None)

        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        cmd = ('rbd', 'import', '--pool', self.POOL, self.TEMPLATE_PATH,
               rbd_name, '--image-format=2', '--id', self.USER,
               '--conf', self.CONF)
        self.assertEqual(fake_processutils.fake_execute_get_log(),
                         [' '.join(cmd)])
        mock_exists.assert_has_calls([mock.call(), mock.call()])
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)

    @mock.patch.object(rbd_utils.RBDDriver, 'resize')
    @mock.patch.object(imagebackend.Rbd, 'verify_base_size')
    @mock.patch.object(imagebackend.Rbd, 'get_disk_size')
    @mock.patch.object(imagebackend.Rbd, 'exists')
    def test_create_image_resize(self, mock_exists, mock_get,
                                 mock_verify, mock_resize):
        fn = mock.MagicMock()
        full_size = self.SIZE * 2

        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)

        image = self.image_class(self.INSTANCE, self.NAME)
        mock_exists.return_value = False
        mock_get.return_value = self.SIZE
        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        cmd = ('rbd', 'import', '--pool', self.POOL, self.TEMPLATE_PATH,
               rbd_name, '--image-format=2', '--id', self.USER,
               '--conf', self.CONF)

        image.create_image(fn, self.TEMPLATE_PATH, full_size)

        self.assertEqual(fake_processutils.fake_execute_get_log(),
                         [' '.join(cmd)])
        mock_exists.assert_has_calls([mock.call(), mock.call()])
        mock_get.assert_called_once_with(rbd_name)
        mock_resize.assert_called_once_with(rbd_name, full_size)
        mock_verify.assert_called_once_with(self.TEMPLATE_PATH, full_size)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)

    @mock.patch.object(imagebackend.Rbd, 'get_disk_size')
    @mock.patch.object(imagebackend.Rbd, 'exists')
    def test_create_image_already_exists(self, mock_exists, mock_get):
        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        image = self.image_class(self.INSTANCE, self.NAME)
        mock_exists.return_value = True
        mock_get.return_value = self.SIZE
        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        fn = mock.MagicMock()

        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        mock_exists.assert_has_calls([mock.call(), mock.call()])
        mock_get.assert_has_calls([mock.call(self.TEMPLATE_PATH),
                                   mock.call(rbd_name)])

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Rbd.exists',
                      lambda *a, **kw: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Rbd.get_disk_size',
                      lambda *a, **kw: self.SIZE)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])

    def test_parent_compatible(self):
        self.assertEqual(utils.getargspec(imagebackend.Image.libvirt_info),
                         utils.getargspec(self.image_class.libvirt_info))

    def test_image_path(self):

        conf = "FakeConf"
        pool = "FakePool"
        user = "FakeUser"

        self.flags(images_rbd_pool=pool, group='libvirt')
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        image = self.image_class(self.INSTANCE, self.NAME)
        rbd_path = "rbd:%s/%s:id=%s:conf=%s" % (pool, image.rbd_name,
                                                user, conf)

        self.assertEqual(image.path, rbd_path)

    def test_get_disk_size(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        with mock.patch.object(image.driver, 'size') as size_mock:
            size_mock.return_value = 2361393152

            self.assertEqual(2361393152, image.get_disk_size(image.path))
            size_mock.assert_called_once_with(image.rbd_name)

    def test_create_image_too_small(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        with mock.patch.object(image, 'driver') as driver_mock:
            driver_mock.exists.return_value = True
            driver_mock.size.return_value = 2

            self.assertRaises(exception.FlavorDiskSmallerThanImage,
                              image.create_image, mock.MagicMock(),
                              self.TEMPLATE_PATH, 1)
            driver_mock.size.assert_called_once_with(image.rbd_name)

    @mock.patch.object(rbd_utils.RBDDriver, "get_mon_addrs")
    def test_libvirt_info(self, mock_mon_addrs):
        def get_mon_addrs():
            hosts = ["server1", "server2"]
            ports = ["1899", "1920"]
            return hosts, ports
        mock_mon_addrs.side_effect = get_mon_addrs

        super(RbdTestCase, self).test_libvirt_info()

    @mock.patch.object(rbd_utils.RBDDriver, "get_mon_addrs")
    def test_get_model(self, mock_mon_addrs):
        pool = "FakePool"
        user = "FakeUser"

        self.flags(images_rbd_pool=pool, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        self.flags(rbd_secret_uuid="3306a5c4-8378-4b3c-aa1f-7b48d3a26172",
                   group='libvirt')

        def get_mon_addrs():
            hosts = ["server1", "server2"]
            ports = ["1899", "1920"]
            return hosts, ports
        mock_mon_addrs.side_effect = get_mon_addrs

        image = self.image_class(self.INSTANCE, self.NAME)
        model = image.get_model(FakeConn())
        self.assertEqual(imgmodel.RBDImage(
            self.INSTANCE["uuid"] + "_fake.vm",
            "FakePool",
            "FakeUser",
            b"MTIzNDU2Cg==",
            ["server1:1899", "server2:1920"]),
                         model)

    def test_import_file(self):
        image = self.image_class(self.INSTANCE, self.NAME)

        @mock.patch.object(image, 'exists')
        @mock.patch.object(image.driver, 'remove_image')
        @mock.patch.object(image.driver, 'import_image')
        def _test(mock_import, mock_remove, mock_exists):
            mock_exists.return_value = True
            image.import_file(self.INSTANCE, mock.sentinel.file,
                              mock.sentinel.remote_name)
            name = '%s_%s' % (self.INSTANCE.uuid,
                              mock.sentinel.remote_name)
            mock_exists.assert_called_once_with()
            mock_remove.assert_called_once_with(name)
            mock_import.assert_called_once_with(mock.sentinel.file, name)
        _test()

    @mock.patch.object(imagebackend.Rbd, 'exists')
    @mock.patch.object(rbd_utils.RBDDriver, 'remove_image')
    @mock.patch.object(rbd_utils.RBDDriver, 'import_image')
    def test_import_file_not_found(self, mock_import, mock_remove,
                                   mock_exists):
        image = self.image_class(self.INSTANCE, self.NAME)
        mock_exists.return_value = False
        image.import_file(self.INSTANCE, mock.sentinel.file,
                          mock.sentinel.remote_name)
        name = '%s_%s' % (self.INSTANCE.uuid,
                          mock.sentinel.remote_name)
        mock_exists.assert_called_once_with()
        self.assertFalse(mock_remove.called)
        mock_import.assert_called_once_with(mock.sentinel.file, name)

    def test_get_parent_pool(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        with mock.patch.object(rbd_utils.RBDDriver, 'parent_info') as mock_pi:
            mock_pi.return_value = [self.POOL, 'fake-image', 'fake-snap']
            parent_pool = image._get_parent_pool(self.CONTEXT, 'fake-image',
                                                 self.FSID)
            self.assertEqual(self.POOL, parent_pool)

    def test_get_parent_pool_no_parent_info(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        rbd_uri = 'rbd://%s/%s/fake-image/fake-snap' % (self.FSID, self.POOL)
        with test.nested(mock.patch.object(rbd_utils.RBDDriver, 'parent_info'),
                         mock.patch.object(imagebackend.IMAGE_API, 'get'),
                         ) as (mock_pi, mock_get):
            mock_pi.side_effect = exception.ImageUnacceptable(image_id='test',
                                                              reason='test')
            mock_get.return_value = {'locations': [{'url': rbd_uri}]}
            parent_pool = image._get_parent_pool(self.CONTEXT, 'fake-image',
                                                 self.FSID)
            self.assertEqual(self.POOL, parent_pool)

    def test_get_parent_pool_non_local_image(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        rbd_uri = 'rbd://remote-cluster/remote-pool/fake-image/fake-snap'
        with test.nested(
                mock.patch.object(rbd_utils.RBDDriver, 'parent_info'),
                mock.patch.object(imagebackend.IMAGE_API, 'get')
        ) as (mock_pi, mock_get):
            mock_pi.side_effect = exception.ImageUnacceptable(image_id='test',
                                                              reason='test')
            mock_get.return_value = {'locations': [{'url': rbd_uri}]}
            self.assertRaises(exception.ImageUnacceptable,
                              image._get_parent_pool, self.CONTEXT,
                              'fake-image', self.FSID)

    def test_direct_snapshot(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        test_snap = 'rbd://%s/%s/fake-image-id/snap' % (self.FSID, self.POOL)
        with test.nested(
                mock.patch.object(rbd_utils.RBDDriver, 'get_fsid',
                                  return_value=self.FSID),
                mock.patch.object(image, '_get_parent_pool',
                                  return_value=self.POOL),
                mock.patch.object(rbd_utils.RBDDriver, 'create_snap'),
                mock.patch.object(rbd_utils.RBDDriver, 'clone'),
                mock.patch.object(rbd_utils.RBDDriver, 'flatten'),
                mock.patch.object(image, 'cleanup_direct_snapshot')
        ) as (mock_fsid, mock_parent, mock_create_snap, mock_clone,
              mock_flatten, mock_cleanup):
            location = image.direct_snapshot(self.CONTEXT, 'fake-snapshot',
                                             'fake-format', 'fake-image-id',
                                             'fake-base-image')
            mock_fsid.assert_called_once_with()
            mock_parent.assert_called_once_with(self.CONTEXT,
                                                'fake-base-image',
                                                self.FSID)
            mock_create_snap.assert_has_calls([mock.call(image.rbd_name,
                                                         'fake-snapshot',
                                                         protect=True),
                                               mock.call('fake-image-id',
                                                         'snap',
                                                         pool=self.POOL,
                                                         protect=True)])
            mock_clone.assert_called_once_with(mock.ANY, 'fake-image-id',
                                               dest_pool=self.POOL)
            mock_flatten.assert_called_once_with('fake-image-id',
                                                 pool=self.POOL)
            mock_cleanup.assert_called_once_with(mock.ANY)
            self.assertEqual(test_snap, location)

    def test_direct_snapshot_cleans_up_on_failures(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        test_snap = 'rbd://%s/%s/%s/snap' % (self.FSID, image.pool,
                                             image.rbd_name)
        with test.nested(
                mock.patch.object(rbd_utils.RBDDriver, 'get_fsid',
                                  return_value=self.FSID),
                mock.patch.object(image, '_get_parent_pool',
                                  return_value=self.POOL),
                mock.patch.object(rbd_utils.RBDDriver, 'create_snap'),
                mock.patch.object(rbd_utils.RBDDriver, 'clone',
                                  side_effect=exception.Forbidden('testing')),
                mock.patch.object(rbd_utils.RBDDriver, 'flatten'),
                mock.patch.object(image, 'cleanup_direct_snapshot')) as (
                mock_fsid, mock_parent, mock_create_snap, mock_clone,
                mock_flatten, mock_cleanup):
            self.assertRaises(exception.Forbidden, image.direct_snapshot,
                              self.CONTEXT, 'snap', 'fake-format',
                              'fake-image-id', 'fake-base-image')
            mock_create_snap.assert_called_once_with(image.rbd_name, 'snap',
                                                     protect=True)
            self.assertFalse(mock_flatten.called)
            mock_cleanup.assert_called_once_with(dict(url=test_snap))

    def test_cleanup_direct_snapshot(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        test_snap = 'rbd://%s/%s/%s/snap' % (self.FSID, image.pool,
                                             image.rbd_name)
        with test.nested(
                mock.patch.object(rbd_utils.RBDDriver, 'remove_snap'),
                mock.patch.object(rbd_utils.RBDDriver, 'destroy_volume')
        ) as (mock_rm, mock_destroy):
            # Ensure that the method does nothing when no location is provided
            image.cleanup_direct_snapshot(None)
            self.assertFalse(mock_rm.called)

            # Ensure that destroy_volume is not called
            image.cleanup_direct_snapshot(dict(url=test_snap))
            mock_rm.assert_called_once_with(image.rbd_name, 'snap', force=True,
                                            ignore_errors=False,
                                            pool=image.pool)
            self.assertFalse(mock_destroy.called)

    def test_cleanup_direct_snapshot_destroy_volume(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        test_snap = 'rbd://%s/%s/%s/snap' % (self.FSID, image.pool,
                                             image.rbd_name)
        with test.nested(
                mock.patch.object(rbd_utils.RBDDriver, 'remove_snap'),
                mock.patch.object(rbd_utils.RBDDriver, 'destroy_volume')
        ) as (mock_rm, mock_destroy):
            # Ensure that destroy_volume is called
            image.cleanup_direct_snapshot(dict(url=test_snap),
                                          also_destroy_volume=True)
            mock_rm.assert_called_once_with(image.rbd_name, 'snap',
                                            force=True,
                                            ignore_errors=False,
                                            pool=image.pool)
            mock_destroy.assert_called_once_with(image.rbd_name,
                                                 pool=image.pool)


class PloopTestCase(_ImageTestCase, test.NoDBTestCase):
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Ploop
        super(PloopTestCase, self).setUp()
        self.utils = imagebackend.utils

    @mock.patch.object(imagebackend.fileutils, 'ensure_tree')
    @mock.patch.object(os.path, 'exists')
    def test_cache(self, mock_exists, mock_ensure):
        mock_exists.side_effect = [False, False, False]
        exist_calls = [mock.call(self.TEMPLATE_DIR),
                       mock.call(self.PATH), mock.call(self.TEMPLATE_PATH)]
        fn = mock.MagicMock()
        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)

        image.cache(fn, self.TEMPLATE)

        mock_ensure.assert_called_once_with(self.TEMPLATE_DIR)
        mock_exists.assert_has_calls(exist_calls)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH)

    @mock.patch.object(imagebackend.Ploop, 'get_disk_size',
                       return_value=2048)
    @mock.patch.object(imagebackend.utils, 'synchronized')
    @mock.patch.object(fake_libvirt_utils, 'copy_image')
    @mock.patch('nova.privsep.libvirt.ploop_restore_descriptor')
    @mock.patch.object(imagebackend.disk, 'extend')
    def test_create_image(self, mock_extend, mock_ploop_restore_descriptor,
                          mock_copy, mock_sync, mock_get):
        mock_sync.side_effect = lambda *a, **kw: self._fake_deco
        fn = mock.MagicMock()
        img_path = os.path.join(self.PATH, "root.hds")
        image = self.image_class(self.INSTANCE, self.NAME)

        image.create_image(fn, self.TEMPLATE_PATH, 2048, image_id=None)

        mock_copy.assert_called_once_with(self.TEMPLATE_PATH, img_path)
        mock_ploop_restore_descriptor.assert_called_once_with(self.PATH,
                                                              img_path,
                                                              "raw")
        self.assertTrue(mock_sync.called)
        fn.assert_called_once_with(target=self.TEMPLATE_PATH, image_id=None)
        mock_extend.assert_called_once_with(
            imgmodel.LocalFileImage(self.PATH, imgmodel.FORMAT_PLOOP),
            2048)

    def test_create_image_generated(self):
        fn = mock.Mock()
        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, 2048, ephemeral_size=2)
        fn.assert_called_with(target=self.PATH,
                              ephemeral_size=2)

    def test_prealloc_image(self):
        self.flags(preallocate_images='space')
        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stub_out('os.path.exists', lambda _: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Ploop.exists',
                      lambda *a, **kw: True)
        self.stub_out('nova.virt.libvirt.imagebackend.Ploop.get_disk_size',
                      lambda *a, **kw: self.SIZE)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)


class BackendTestCase(test.NoDBTestCase):
    INSTANCE = objects.Instance(id=1, uuid=uuidutils.generate_uuid())
    NAME = 'fake-name.suffix'

    def setUp(self):
        super(BackendTestCase, self).setUp()
        self.flags(enabled=False, group='ephemeral_storage_encryption')
        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)
        self.INSTANCE['ephemeral_key_uuid'] = None

    def get_image(self, use_cow, image_type):
        return imagebackend.Backend(use_cow).by_name(self.INSTANCE, self.NAME,
                                                     image_type)

    def _test_image(self, image_type, image_not_cow, image_cow):
        image1 = self.get_image(False, image_type)
        image2 = self.get_image(True, image_type)

        def assertIsInstance(instance, class_object):
            failure = ('Expected %s,' +
                       ' but got %s.') % (class_object.__name__,
                                          instance.__class__.__name__)
            self.assertIsInstance(instance, class_object, msg=failure)

        assertIsInstance(image1, image_not_cow)
        assertIsInstance(image2, image_cow)

    def test_image_flat(self):
        self._test_image('raw', imagebackend.Flat, imagebackend.Flat)

    def test_image_flat_preallocate_images(self):
        self.flags(preallocate_images='space')
        raw = imagebackend.Flat(self.INSTANCE, 'fake_disk', '/tmp/xyz')
        self.assertTrue(raw.preallocate)

    def test_image_flat_native_io(self):
        self.flags(preallocate_images="space")
        raw = imagebackend.Flat(self.INSTANCE, 'fake_disk', '/tmp/xyz')
        self.assertEqual(raw.driver_io, "native")

    def test_image_qcow2(self):
        self._test_image('qcow2', imagebackend.Qcow2, imagebackend.Qcow2)

    def test_image_qcow2_preallocate_images(self):
        self.flags(preallocate_images='space')
        qcow = imagebackend.Qcow2(self.INSTANCE, 'fake_disk', '/tmp/xyz')
        self.assertTrue(qcow.preallocate)

    def test_image_qcow2_native_io(self):
        self.flags(preallocate_images="space")
        qcow = imagebackend.Qcow2(self.INSTANCE, 'fake_disk', '/tmp/xyz')
        self.assertEqual(qcow.driver_io, "native")

    def test_image_lvm_native_io(self):
        def _test_native_io(is_sparse, driver_io):
            self.flags(images_volume_group='FakeVG', group='libvirt')
            self.flags(sparse_logical_volumes=is_sparse, group='libvirt')
            lvm = imagebackend.Lvm(self.INSTANCE, 'fake_disk')
            self.assertEqual(lvm.driver_io, driver_io)
        _test_native_io(is_sparse=False, driver_io="native")
        _test_native_io(is_sparse=True, driver_io=None)

    def test_image_lvm(self):
        self.flags(images_volume_group='FakeVG', group='libvirt')
        self._test_image('lvm', imagebackend.Lvm, imagebackend.Lvm)

    @mock.patch.object(rbd_utils, 'rbd')
    @mock.patch.object(rbd_utils, 'rados')
    def test_image_rbd(self, mock_rados, mock_rbd):
        conf = "FakeConf"
        pool = "FakePool"
        self.flags(images_rbd_pool=pool, group='libvirt')
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self._test_image('rbd', imagebackend.Rbd, imagebackend.Rbd)

    def test_image_default(self):
        self._test_image('default', imagebackend.Flat, imagebackend.Qcow2)


class UtimeWorkaroundTestCase(test.NoDBTestCase):
    ERROR_STUB = "sentinel.path: [Errno 13] Permission Denied"

    def setUp(self):
        super(UtimeWorkaroundTestCase, self).setUp()
        self.mock_utime = self.useFixture(
                fixtures.MockPatch('nova.privsep.path.utime')).mock

    def test_update_utime_no_error(self):
        # If utime doesn't raise an error we shouldn't raise or log anything
        imagebackend._update_utime_ignore_eacces(mock.sentinel.path)
        self.mock_utime.assert_called_once_with(mock.sentinel.path)
        self.assertNotIn(self.ERROR_STUB, self.stdlog.logger.output)

    def test_update_utime_eacces(self):
        # If utime raises EACCES we should log the error, but ignore it
        e = OSError()
        e.errno = errno.EACCES
        e.strerror = "Permission Denied"
        self.mock_utime.side_effect = e

        imagebackend._update_utime_ignore_eacces(mock.sentinel.path)
        self.mock_utime.assert_called_once_with(mock.sentinel.path)
        self.assertIn(self.ERROR_STUB, self.stdlog.logger.output)

    def test_update_utime_eio(self):
        # If utime raises any other error we should raise it
        e = OSError()
        e.errno = errno.EIO
        e.strerror = "IO Error"
        self.mock_utime.side_effect = e

        ex = self.assertRaises(
            OSError, imagebackend._update_utime_ignore_eacces,
            mock.sentinel.path)
        self.assertIs(ex, e)

        self.mock_utime.assert_called_once_with(mock.sentinel.path)
        self.assertNotIn(self.ERROR_STUB, self.stdlog.logger.output)
