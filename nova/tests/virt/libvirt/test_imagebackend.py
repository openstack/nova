# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import os
import shutil
import tempfile

import fixtures
from oslo.config import cfg

from inspect import getargspec

from nova import exception
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_processutils
from nova.tests.virt.libvirt import fake_libvirt_utils
from nova import utils
from nova.virt.libvirt import imagebackend

CONF = cfg.CONF


class _ImageTestCase(object):

    def mock_create_image(self, image):
        def create_image(fn, base, size, *args, **kwargs):
            fn(target=base, *args, **kwargs)
        image.create_image = create_image

    def setUp(self):
        super(_ImageTestCase, self).setUp()
        self.INSTANCES_PATH = tempfile.mkdtemp(suffix='instances')
        self.flags(disable_process_locking=True,
                   instances_path=self.INSTANCES_PATH)
        self.INSTANCE = {'name': 'instance',
                         'uuid': uuidutils.generate_uuid()}
        self.DISK_INFO_PATH = os.path.join(self.INSTANCES_PATH,
                                           self.INSTANCE['uuid'], 'disk.info')
        self.NAME = 'fake.vm'
        self.TEMPLATE = 'template'

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

        def fake_chown(path, owner_uid=None):
            return None
        self.stubs.Set(utils, 'chown', fake_chown)

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


class RawTestCase(_ImageTestCase, test.NoDBTestCase):

    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Raw
        super(RawTestCase, self).setUp()
        self.stubs.Set(imagebackend.Raw, 'correct_format', lambda _: None)

        def fake_chown(path, owner_uid=None):
            return None
        self.stubs.Set(utils, 'chown', fake_chown)

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
        fn = self.mox.CreateMockAnything()
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

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

    def test_create_image_extend(self):
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

        def fake_chown(path, owner_uid=None):
            return None
        self.stubs.Set(utils, 'chown', fake_chown)

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

    def test_resolve_driver_format(self):
        image = self.image_class(self.INSTANCE, self.NAME)
        driver_format = image.resolve_driver_format()
        self.assertEqual(driver_format, 'raw')


class Qcow2TestCase(_ImageTestCase, test.NoDBTestCase):
    SIZE = 1024 * 1024 * 1024

    def setUp(self):
        self.image_class = imagebackend.Qcow2
        super(Qcow2TestCase, self).setUp()
        self.QCOW2_BASE = (self.TEMPLATE_PATH +
                           '_%d' % (self.SIZE / (1024 * 1024 * 1024)))

        def fake_chown(path, owner_uid=None):
            return None
        self.stubs.Set(utils, 'chown', fake_chown)

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
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

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
        self.mox.StubOutWithMock(imagebackend.disk, 'get_disk_size')
        if self.OLD_STYLE_INSTANCE_PATH:
            os.path.exists(self.OLD_STYLE_INSTANCE_PATH).AndReturn(False)
        os.path.exists(self.DISK_INFO_PATH).AndReturn(False)
        os.path.exists(self.INSTANCES_PATH).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        imagebackend.disk.get_disk_size(self.TEMPLATE_PATH
                                       ).AndReturn(self.SIZE)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.assertRaises(exception.InstanceTypeDiskTooSmall,
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


class LvmTestCase(_ImageTestCase, test.NoDBTestCase):
    VG = 'FakeVG'
    TEMPLATE_SIZE = 512
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Lvm
        super(LvmTestCase, self).setUp()
        self.flags(libvirt_images_volume_group=self.VG)
        self.LV = '%s_%s' % (self.INSTANCE['name'], self.NAME)
        self.OLD_STYLE_INSTANCE_PATH = None
        self.PATH = os.path.join('/dev', self.VG, self.LV)

        self.disk = imagebackend.disk
        self.utils = imagebackend.utils
        self.libvirt_utils = imagebackend.libvirt_utils

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(self.disk, 'resize2fs')
        self.mox.StubOutWithMock(self.libvirt_utils, 'create_lvm_image')
        self.mox.StubOutWithMock(self.disk, 'get_disk_size')
        self.mox.StubOutWithMock(self.utils, 'execute')
        return fn

    def _create_image(self, sparse):
        fn = self.prepare_mocks()
        fn(max_size=None, target=self.TEMPLATE_PATH)
        self.libvirt_utils.create_lvm_image(self.VG,
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
        self.libvirt_utils.create_lvm_image(self.VG, self.LV,
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
        self.libvirt_utils.create_lvm_image(self.VG, self.LV,
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
        self.flags(libvirt_sparse_logical_volumes=True)
        self._create_image(True)

    def test_create_image_generated(self):
        self._create_image_generated(False)

    def test_create_image_generated_sparsed(self):
        self.flags(libvirt_sparse_logical_volumes=True)
        self._create_image_generated(True)

    def test_create_image_resize(self):
        self._create_image_resize(False)

    def test_create_image_resize_sparsed(self):
        self.flags(libvirt_sparse_logical_volumes=True)
        self._create_image_resize(True)

    def test_create_image_negative(self):
        fn = self.prepare_mocks()
        fn(max_size=self.SIZE, target=self.TEMPLATE_PATH)
        self.libvirt_utils.create_lvm_image(self.VG,
                                            self.LV,
                                            self.SIZE,
                                            sparse=False
                                            ).AndRaise(RuntimeError())
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        self.mox.StubOutWithMock(self.libvirt_utils, 'remove_logical_volumes')
        self.libvirt_utils.remove_logical_volumes(self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)

        self.assertRaises(RuntimeError, image.create_image, fn,
                          self.TEMPLATE_PATH, self.SIZE)
        self.mox.VerifyAll()

    def test_create_image_generated_negative(self):
        fn = self.prepare_mocks()
        fn(target=self.PATH,
           ephemeral_size=None).AndRaise(RuntimeError())
        self.libvirt_utils.create_lvm_image(self.VG,
                                            self.LV,
                                            self.SIZE,
                                            sparse=False)
        self.mox.StubOutWithMock(self.libvirt_utils, 'remove_logical_volumes')
        self.libvirt_utils.remove_logical_volumes(self.PATH)
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
        self.flags(libvirt_images_rbd_pool=self.POOL)
        self.flags(rbd_user=self.USER)
        self.flags(libvirt_images_rbd_ceph_conf=self.CONF)
        self.libvirt_utils = imagebackend.libvirt_utils
        self.utils = imagebackend.utils
        self.rbd = self.mox.CreateMockAnything()
        self.rados = self.mox.CreateMockAnything()

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend, 'rbd')
        self.mox.StubOutWithMock(imagebackend, 'rados')
        return fn

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
        fn = self.mox.CreateMockAnything()
        self.mox.ReplayAll()

        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
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
        fn = self.prepare_mocks()
        fn(max_size=None, rbd=self.rbd, target=self.TEMPLATE_PATH)

        self.rbd.RBD_FEATURE_LAYERING = 1

        self.mox.StubOutWithMock(imagebackend.disk, 'get_disk_size')
        imagebackend.disk.get_disk_size(self.TEMPLATE_PATH
                                       ).AndReturn(self.SIZE)
        rbd_name = "%s/%s" % (self.INSTANCE['name'], self.NAME)
        cmd = ('--pool', self.POOL, self.TEMPLATE_PATH,
               rbd_name, '--new-format', '--id', self.USER,
               '--conf', self.CONF)
        self.libvirt_utils.import_rbd_image(self.TEMPLATE_PATH, *cmd)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None, rbd=self.rbd)

        self.mox.VerifyAll()

    def test_prealloc_image(self):
        CONF.set_override('preallocate_images', 'space')

        fake_processutils.fake_execute_clear_log()
        fake_processutils.stub_out_processutils_execute(self.stubs)
        self.mox.StubOutWithMock(imagebackend, 'rbd')
        self.mox.StubOutWithMock(imagebackend, 'rados')
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
        self.assertEqual(getargspec(imagebackend.Image.libvirt_info),
             getargspec(self.image_class.libvirt_info))


class BackendTestCase(test.NoDBTestCase):
    INSTANCE = {'name': 'fake-instance',
                'uuid': uuidutils.generate_uuid()}
    NAME = 'fake-name.suffix'

    def setUp(self):
        super(BackendTestCase, self).setUp()

        def fake_chown(path, owner_uid=None):
            return None
        self.stubs.Set(utils, 'chown', fake_chown)

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
            self.assertTrue(isinstance(instance, class_object), failure)

        assertIsInstance(image1, image_not_cow)
        assertIsInstance(image2, image_cow)

    def test_image_raw(self):
        self._test_image('raw', imagebackend.Raw, imagebackend.Raw)

    def test_image_qcow2(self):
        self._test_image('qcow2', imagebackend.Qcow2, imagebackend.Qcow2)

    def test_image_lvm(self):
        self.flags(libvirt_images_volume_group='FakeVG')
        self._test_image('lvm', imagebackend.Lvm, imagebackend.Lvm)

    def test_image_rbd(self):
        conf = "FakeConf"
        pool = "FakePool"
        self.flags(libvirt_images_rbd_pool=pool)
        self.flags(libvirt_images_rbd_ceph_conf=conf)
        self._test_image('rbd', imagebackend.Rbd, imagebackend.Rbd)

    def test_image_default(self):
        self._test_image('default', imagebackend.Raw, imagebackend.Qcow2)
