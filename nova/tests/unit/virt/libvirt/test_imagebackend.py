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

import contextlib
import inspect
import os
import shutil
import tempfile

import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_utils import units

from nova import context
from nova import exception
from nova import keymgr
from nova.openstack.common import imageutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit import fake_processutils
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import rbd_utils

CONF = cfg.CONF
CONF.import_opt('fixed_key', 'nova.keymgr.conf_key_mgr', group='keymgr')


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
        self.INSTANCE = {'name': 'instance',
                         'uuid': uuidutils.generate_uuid()}
        self.DISK_INFO_PATH = os.path.join(self.INSTANCES_PATH,
                                           self.INSTANCE['uuid'], 'disk.info')
        self.NAME = 'fake.vm'
        self.TEMPLATE = 'template'
        self.CONTEXT = context.get_admin_context()

        self.OLD_STYLE_INSTANCE_PATH = \
            fake_libvirt_utils.get_instance_path(self.INSTANCE, forceold=True)
        self.PATH = os.path.join(
            fake_libvirt_utils.get_instance_path(self.INSTANCE), self.NAME)

        # TODO(mikal): rename template_dir to base_dir and template_path
        # to cached_image_path. This will be less confusing.
        self.TEMPLATE_DIR = os.path.join(CONF.instances_path, '_base')
        self.TEMPLATE_PATH = os.path.join(self.TEMPLATE_DIR, 'template')

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.libvirt_utils',
            fake_libvirt_utils))

    def tearDown(self):
        super(_ImageTestCase, self).tearDown()
        shutil.rmtree(self.INSTANCES_PATH)

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(os, 'access', lambda p, w: True)

        # Call twice to verify testing fallocate is only called once.
        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)
        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(),
            ['fallocate -n -l 1 %s.fallocate_test' % self.PATH,
             'fallocate -n -l %s %s' % (self.SIZE, self.PATH),
             'fallocate -n -l %s %s' % (self.SIZE, self.PATH)])

    def test_prealloc_image_without_write_access(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stubs.Set(image, 'check_image_exists', lambda: True)
        self.stubs.Set(image, '_can_fallocate', lambda: True)
        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(os, 'access', lambda p, w: False)

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


class RawTestCase(_ImageTestCase, test.NoDBTestCase):

    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Raw
        super(RawTestCase, self).setUp()
        self.stubs.Set(imagebackend.Raw, 'correct_format', lambda _: None)

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend.utils.synchronized,
                                 '__call__')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils, 'copy_image')
        self.mox.StubOutWithMock(imagebackend.disk, 'extend')
        return fn

    def test_cache(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        imagebackend.fileutils.ensure_tree(self.TEMPLATE_DIR)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_image_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_template_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_create_image(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH, max_size=None, image_id=None)
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH, self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None, image_id=None)

        self.mox.VerifyAll()

    def test_create_image_generated(self):
        fn = self.prepare_mocks()
        fn(target=self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None)

        self.mox.VerifyAll()

    @mock.patch.object(images, 'qemu_img_info',
                       return_value=imageutils.QemuImgInfo())
    def test_create_image_extend(self, fake_qemu_img_info):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH, image_id=None)
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH, self.PATH)
        imagebackend.disk.extend(self.PATH, self.SIZE, use_cow=False)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE, image_id=None)

        self.mox.VerifyAll()

    def test_correct_format(self):
        self.stubs.UnsetAll()

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.images, 'qemu_img_info')

        os.path.exists(self.PATH).AndReturn(True)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        info = self.mox.CreateMockAnything()
        info.file_format = 'foo'
        imagebackend.images.qemu_img_info(self.PATH).AndReturn(info)
        os.path.exists(CONF.instances_path).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME, path=self.PATH)
        self.assertEqual(image.driver_format, 'foo')

        self.mox.VerifyAll()

    @mock.patch.object(images, 'qemu_img_info',
                       side_effect=exception.InvalidDiskInfo(
                           reason='invalid path'))
    def test_resolve_driver_format(self, fake_qemu_img_info):
        image = self.image_class(self.INSTANCE, self.NAME)
        driver_format = image.resolve_driver_format()
        self.assertEqual(driver_format, 'raw')


class Qcow2TestCase(_ImageTestCase, test.NoDBTestCase):
    SIZE = units.Gi

    def setUp(self):
        self.image_class = imagebackend.Qcow2
        super(Qcow2TestCase, self).setUp()
        self.QCOW2_BASE = (self.TEMPLATE_PATH +
                           '_%d' % (self.SIZE / units.Gi))

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend.utils.synchronized,
                                 '__call__')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils,
                                 'create_cow_image')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils, 'copy_image')
        self.mox.StubOutWithMock(imagebackend.disk, 'extend')
        return fn

    def test_cache(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(CONF.instances_path).AndReturn(True)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_image_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_template_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_create_image(self):
        fn = self.prepare_mocks()
        fn(max_size=None, target=self.TEMPLATE_PATH)
        imagebackend.libvirt_utils.create_cow_image(self.TEMPLATE_PATH,
                                                    self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None)

        self.mox.VerifyAll()

    def test_create_image_with_size(self):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(False)
        imagebackend.libvirt_utils.create_cow_image(self.TEMPLATE_PATH,
                                                    self.PATH)
        imagebackend.disk.extend(self.PATH, self.SIZE, use_cow=True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_create_image_too_small(self):
        fn = self.prepare_mocks()
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.Qcow2, 'get_disk_size')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        imagebackend.Qcow2.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.SIZE)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.assertRaises(exception.FlavorDiskTooSmall,
                          image.create_image, fn, self.TEMPLATE_PATH, 1)
        self.mox.VerifyAll()

    def test_generate_resized_backing_files(self):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils,
                                 'get_disk_backing_file')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(CONF.instances_path).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(True)

        imagebackend.libvirt_utils.get_disk_backing_file(self.PATH)\
            .AndReturn(self.QCOW2_BASE)
        os.path.exists(self.QCOW2_BASE).AndReturn(False)
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH,
                                              self.QCOW2_BASE)
        imagebackend.disk.extend(self.QCOW2_BASE, self.SIZE, use_cow=True)

        os.path.exists(self.PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_qcow2_exists_and_has_no_backing_file(self):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils,
                                 'get_disk_backing_file')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)

        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(True)

        imagebackend.libvirt_utils.get_disk_backing_file(self.PATH)\
            .AndReturn(None)
        os.path.exists(self.PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_resolve_driver_format(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        driver_format = image.resolve_driver_format()
        self.assertEqual(driver_format, 'qcow2')


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
        self.OLD_STYLE_INSTANCE_PATH = None
        self.PATH = os.path.join('/dev', self.VG, self.LV)
        self.disk = imagebackend.disk
        self.utils = imagebackend.utils
        self.lvm = imagebackend.lvm

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(self.disk, 'resize2fs')
        self.mox.StubOutWithMock(self.lvm, 'create_volume')
        self.mox.StubOutWithMock(self.disk, 'get_disk_size')
        self.mox.StubOutWithMock(self.utils, 'execute')
        return fn

    def _create_image(self, sparse):
        fn = self.prepare_mocks()
        fn(max_size=None, target=self.TEMPLATE_PATH)
        self.lvm.create_volume(self.VG,
                               self.LV,
                               self.TEMPLATE_SIZE,
                               sparse=sparse)
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        cmd = ('qemu-img', 'convert', '-O', 'raw', self.TEMPLATE_PATH,
               self.PATH)
        self.utils.execute(*cmd, run_as_root=True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None)

        self.mox.VerifyAll()

    def _create_image_generated(self, sparse):
        fn = self.prepare_mocks()
        self.lvm.create_volume(self.VG, self.LV,
                               self.SIZE, sparse=sparse)
        fn(target=self.PATH, ephemeral_size=None)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH,
                self.SIZE, ephemeral_size=None)

        self.mox.VerifyAll()

    def _create_image_resize(self, sparse):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.lvm.create_volume(self.VG, self.LV,
                               self.SIZE, sparse=sparse)
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        cmd = ('qemu-img', 'convert', '-O', 'raw', self.TEMPLATE_PATH,
               self.PATH)
        self.utils.execute(*cmd, run_as_root=True)
        self.disk.resize2fs(self.PATH, run_as_root=True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_cache(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)

        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        imagebackend.fileutils.ensure_tree(self.TEMPLATE_DIR)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_image_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

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
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.lvm.create_volume(self.VG,
                               self.LV,
                               self.SIZE,
                               sparse=False
                               ).AndRaise(RuntimeError())
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        self.mox.StubOutWithMock(self.lvm, 'remove_volumes')
        self.lvm.remove_volumes([self.PATH])
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(RuntimeError, image.create_image, fn,
                          self.TEMPLATE_PATH, self.SIZE)
        self.mox.VerifyAll()

    def test_create_image_generated_negative(self):
        fn = self.prepare_mocks()
        fn(target=self.PATH,
           ephemeral_size=None).AndRaise(RuntimeError())
        self.lvm.create_volume(self.VG,
                               self.LV,
                               self.SIZE,
                               sparse=False)
        self.mox.StubOutWithMock(self.lvm, 'remove_volumes')
        self.lvm.remove_volumes([self.PATH])
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(RuntimeError, image.create_image, fn,
                          self.TEMPLATE_PATH, self.SIZE,
                          ephemeral_size=None)
        self.mox.VerifyAll()

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(image, 'check_image_exists', lambda: True)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])


class EncryptedLvmTestCase(_ImageTestCase, test.NoDBTestCase):
    VG = 'FakeVG'
    TEMPLATE_SIZE = 512
    SIZE = 1024

    def setUp(self):
        super(EncryptedLvmTestCase, self).setUp()
        self.image_class = imagebackend.Lvm
        self.flags(enabled=True, group='ephemeral_storage_encryption')
        self.flags(cipher='aes-xts-plain64',
                   group='ephemeral_storage_encryption')
        self.flags(key_size=512, group='ephemeral_storage_encryption')
        self.flags(fixed_key='00000000000000000000000000000000'
                             '00000000000000000000000000000000',
                   group='keymgr')
        self.flags(images_volume_group=self.VG, group='libvirt')
        self.LV = '%s_%s' % (self.INSTANCE['uuid'], self.NAME)
        self.OLD_STYLE_INSTANCE_PATH = None
        self.LV_PATH = os.path.join('/dev', self.VG, self.LV)
        self.PATH = os.path.join('/dev/mapper',
            imagebackend.dmcrypt.volume_name(self.LV))
        self.key_manager = keymgr.API()
        self.INSTANCE['ephemeral_key_uuid'] =\
            self.key_manager.create_key(self.CONTEXT)
        self.KEY = self.key_manager.get_key(self.CONTEXT,
            self.INSTANCE['ephemeral_key_uuid']).get_encoded()

        self.lvm = imagebackend.lvm
        self.disk = imagebackend.disk
        self.utils = imagebackend.utils
        self.libvirt_utils = imagebackend.libvirt_utils
        self.dmcrypt = imagebackend.dmcrypt

    def _create_image(self, sparse):
        with contextlib.nested(
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

            image = self.image_class(self.INSTANCE, self.NAME)
            image.create_image(fn, self.TEMPLATE_PATH, self.TEMPLATE_SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(context=self.CONTEXT,
                max_size=self.TEMPLATE_SIZE,
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
            cmd = ('qemu-img',
                   'convert',
                   '-O',
                   'raw',
                   self.TEMPLATE_PATH,
                   self.PATH)
            self.utils.execute.assert_called_with(*cmd, run_as_root=True)

    def _create_image_generated(self, sparse):
        with contextlib.nested(
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
        with contextlib.nested(
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

            image = self.image_class(self.INSTANCE, self.NAME)
            image.create_image(fn, self.TEMPLATE_PATH, self.SIZE,
                context=self.CONTEXT)

            fn.assert_called_with(context=self.CONTEXT, max_size=self.SIZE,
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
            cmd = ('qemu-img',
                   'convert',
                   '-O',
                   'raw',
                   self.TEMPLATE_PATH,
                   self.PATH)
            self.utils.execute.assert_called_with(*cmd, run_as_root=True)
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
        with contextlib.nested(
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
                max_size=self.SIZE,
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
        with contextlib.nested(
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
                max_size=self.SIZE,
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
        with contextlib.nested(
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
        with contextlib.nested(
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
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(image, 'check_image_exists', lambda: True)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])


class RbdTestCase(_ImageTestCase, test.NoDBTestCase):
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
        self.mox.StubOutWithMock(rbd_utils, 'rbd')
        self.mox.StubOutWithMock(rbd_utils, 'rados')

    def test_cache(self):
        image = self.image_class(self.INSTANCE, self.NAME)

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(image, 'check_image_exists')
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        image.check_image_exists().AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        imagebackend.fileutils.ensure_tree(self.TEMPLATE_DIR)
        self.mox.ReplayAll()

        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        fn = self.mox.CreateMockAnything()
        image = self.image_class(self.INSTANCE, self.NAME)

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(image, 'check_image_exists')
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        image.check_image_exists().AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        self.mox.ReplayAll()

        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_image_exists(self):
        image = self.image_class(self.INSTANCE, self.NAME)

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(image, 'check_image_exists')
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        image.check_image_exists().AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_template_exists(self):
        image = self.image_class(self.INSTANCE, self.NAME)

        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(image, 'check_image_exists')
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        image.check_image_exists().AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        self.mox.ReplayAll()

        self.mock_create_image(image)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_create_image(self):
        fn = self.mox.CreateMockAnything()
        fn(max_size=None, target=self.TEMPLATE_PATH)

        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mox.StubOutWithMock(image, 'check_image_exists')
        image.check_image_exists().AndReturn(False)
        image.check_image_exists().AndReturn(False)
        self.mox.ReplayAll()

        image.create_image(fn, self.TEMPLATE_PATH, None)

        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        cmd = ('rbd', 'import', '--pool', self.POOL, self.TEMPLATE_PATH,
               rbd_name, '--new-format', '--id', self.USER,
               '--conf', self.CONF)
        self.assertEqual(fake_processutils.fake_execute_get_log(),
            [' '.join(cmd)])
        self.mox.VerifyAll()

    def test_create_image_resize(self):
        fn = self.mox.CreateMockAnything()
        full_size = self.SIZE * 2
        fn(max_size=full_size, target=self.TEMPLATE_PATH)

        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mox.StubOutWithMock(image, 'check_image_exists')
        image.check_image_exists().AndReturn(False)
        image.check_image_exists().AndReturn(False)
        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        cmd = ('rbd', 'import', '--pool', self.POOL, self.TEMPLATE_PATH,
               rbd_name, '--new-format', '--id', self.USER,
               '--conf', self.CONF)
        self.mox.StubOutWithMock(image, 'get_disk_size')
        image.get_disk_size(rbd_name).AndReturn(self.SIZE)
        self.mox.StubOutWithMock(image.driver, 'resize')
        image.driver.resize(rbd_name, full_size)

        self.mox.ReplayAll()

        image.create_image(fn, self.TEMPLATE_PATH, full_size)

        self.assertEqual(fake_processutils.fake_execute_get_log(),
            [' '.join(cmd)])
        self.mox.VerifyAll()

    def test_create_image_already_exists(self):
        rbd_utils.rbd.RBD_FEATURE_LAYERING = 1

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mox.StubOutWithMock(image, 'check_image_exists')
        image.check_image_exists().AndReturn(True)
        self.mox.StubOutWithMock(image, 'get_disk_size')
        image.get_disk_size(self.TEMPLATE_PATH).AndReturn(self.SIZE)
        image.check_image_exists().AndReturn(True)
        rbd_name = "%s_%s" % (self.INSTANCE['uuid'], self.NAME)
        image.get_disk_size(rbd_name).AndReturn(self.SIZE)

        self.mox.ReplayAll()

        fn = self.mox.CreateMockAnything()
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        def fake_resize(rbd_name, size):
            return

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(image, 'check_image_exists', lambda: True)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)

        self.assertEqual(fake_processutils.fake_execute_get_log(), [])

    def test_parent_compatible(self):
        self.assertEqual(inspect.getargspec(imagebackend.Image.libvirt_info),
                         inspect.getargspec(self.image_class.libvirt_info))

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


class PloopTestCase(_ImageTestCase, test.NoDBTestCase):
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Ploop
        super(PloopTestCase, self).setUp()
        self.utils = imagebackend.utils
        self.stubs.Set(imagebackend.Ploop, 'get_disk_size', lambda a, b: 2048)

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend.utils.synchronized,
                                 '__call__')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils, 'copy_image')
        self.mox.StubOutWithMock(self.utils, 'execute')
        return fn

    def test_cache(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.fileutils, 'ensure_tree')
        imagebackend.fileutils.ensure_tree(self.TEMPLATE_DIR)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_create_image(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH, max_size=2048, image_id=None)
        img_path = os.path.join(self.PATH, "root.hds")
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH, img_path)
        self.utils.execute("ploop", "restore-descriptor", "-f", "raw",
                           self.PATH, img_path)
        self.utils.execute("ploop", "grow", '-s', "2K",
                           os.path.join(self.PATH, "DiskDescriptor.xml"),
                           run_as_root=True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, 2048, image_id=None)

        self.mox.VerifyAll()

    def test_prealloc_image(self):
        self.flags(preallocate_images='space')
        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        image = self.image_class(self.INSTANCE, self.NAME)

        def fake_fetch(target, *args, **kwargs):
            return

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(image, 'check_image_exists', lambda: True)

        image.cache(fake_fetch, self.TEMPLATE_PATH, self.SIZE)


class BackendTestCase(test.NoDBTestCase):
    INSTANCE = {'name': 'fake-instance',
                'uuid': uuidutils.generate_uuid()}
    NAME = 'fake-name.suffix'

    def setUp(self):
        super(BackendTestCase, self).setUp()
        self.flags(enabled=False, group='ephemeral_storage_encryption')
        self.INSTANCE['ephemeral_key_uuid'] = None

    def get_image(self, use_cow, image_type):
        return imagebackend.Backend(use_cow).image(self.INSTANCE,
                                                   self.NAME,
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

    def test_image_raw(self):
        self._test_image('raw', imagebackend.Raw, imagebackend.Raw)

    def test_image_qcow2(self):
        self._test_image('qcow2', imagebackend.Qcow2, imagebackend.Qcow2)

    def test_image_lvm(self):
        self.flags(images_volume_group='FakeVG', group='libvirt')
        self._test_image('lvm', imagebackend.Lvm, imagebackend.Lvm)

    def test_image_rbd(self):
        conf = "FakeConf"
        pool = "FakePool"
        self.flags(images_rbd_pool=pool, group='libvirt')
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.mox.StubOutWithMock(rbd_utils, 'rbd')
        self.mox.StubOutWithMock(rbd_utils, 'rados')
        self._test_image('rbd', imagebackend.Rbd, imagebackend.Rbd)

    def test_image_default(self):
        self._test_image('default', imagebackend.Raw, imagebackend.Qcow2)


class UtilTestCase(test.NoDBTestCase):
    def test_get_hw_disk_discard(self):
        self.assertEqual('unmap', imagebackend.get_hw_disk_discard("unmap"))
        self.assertEqual('ignore', imagebackend.get_hw_disk_discard("ignore"))
        self.assertIsNone(imagebackend.get_hw_disk_discard(None))
        self.assertRaises(RuntimeError, imagebackend.get_hw_disk_discard,
                          "fake")
