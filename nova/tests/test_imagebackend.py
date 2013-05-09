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

from nova import exception
from nova import flags
from nova import test
from nova.tests import fake_libvirt_utils
from nova.virt.libvirt import imagebackend

FLAGS = flags.FLAGS


class _ImageTestCase(test.TestCase):
    INSTANCES_PATH = '/fake'

    def mock_create_image(self, image):
        def create_image(fn, base, size, *args, **kwargs):
            fn(target=base, *args, **kwargs)
        image.create_image = create_image

    def setUp(self):
        super(_ImageTestCase, self).setUp()
        self.flags(disable_process_locking=True,
                   instances_path=self.INSTANCES_PATH)
        self.INSTANCE = 'instance'
        self.NAME = 'fake.vm'
        self.TEMPLATE = 'template'

        self.PATH = os.path.join(FLAGS.instances_path, self.INSTANCE,
                                 self.NAME)
        self.TEMPLATE_DIR = os.path.join(FLAGS.instances_path,
                                         '_base')
        self.TEMPLATE_PATH = os.path.join(self.TEMPLATE_DIR, 'template')

        imagebackend.libvirt_utils = fake_libvirt_utils

    def test_cache(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(False)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.utils, 'ensure_tree')
        imagebackend.utils.ensure_tree(self.TEMPLATE_DIR)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_image_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.PATH).AndReturn(True)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.cache(None, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_base_dir_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(False)
        fn = self.mox.CreateMockAnything()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(imagebackend.utils, 'ensure_tree')
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()

    def test_cache_template_exists(self):
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.PATH).AndReturn(False)
        os.path.exists(self.TEMPLATE_DIR).AndReturn(True)
        os.path.exists(self.TEMPLATE_PATH).AndReturn(True)
        fn = self.mox.CreateMockAnything()
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.mock_create_image(image)
        image.cache(fn, self.TEMPLATE)

        self.mox.VerifyAll()


class RawTestCase(_ImageTestCase):

    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Raw
        super(RawTestCase, self).setUp()

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend.utils.synchronized, '__call__')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils, 'copy_image')
        self.mox.StubOutWithMock(imagebackend.disk, 'extend')
        return fn

    def test_create_image(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH, image_id=None)
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
        fn(target=self.TEMPLATE_PATH, image_id=None)
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH, self.PATH)
        imagebackend.disk.extend(self.PATH, self.SIZE)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE, image_id=None)

        self.mox.VerifyAll()


class Qcow2TestCase(_ImageTestCase):
    SIZE = 1024 * 1024 * 1024

    def setUp(self):
        self.image_class = imagebackend.Qcow2
        super(Qcow2TestCase, self).setUp()
        self.QCOW2_BASE = (self.TEMPLATE_PATH +
                           '_%d' % (self.SIZE / (1024 * 1024 * 1024)))

    def prepare_mocks(self):
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(imagebackend.utils.synchronized, '__call__')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils,
                                 'create_cow_image')
        self.mox.StubOutWithMock(imagebackend.libvirt_utils, 'copy_image')
        self.mox.StubOutWithMock(imagebackend.disk, 'extend')
        return fn

    def test_create_image(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH)
        imagebackend.libvirt_utils.create_cow_image(self.TEMPLATE_PATH,
                                                    self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, None)

        self.mox.VerifyAll()

    def test_create_image_with_size(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.disk, 'get_disk_size')
        os.path.exists(self.QCOW2_BASE).AndReturn(False)
        imagebackend.disk.get_disk_size(self.TEMPLATE_PATH
                                       ).AndReturn(self.SIZE)
        imagebackend.libvirt_utils.copy_image(self.TEMPLATE_PATH,
                                              self.QCOW2_BASE)
        imagebackend.disk.extend(self.QCOW2_BASE, self.SIZE)
        imagebackend.libvirt_utils.create_cow_image(self.QCOW2_BASE,
                                                    self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()

    def test_create_image_too_small(self):
        self.mox.StubOutWithMock(imagebackend.disk, 'get_disk_size')
        imagebackend.disk.get_disk_size(self.TEMPLATE_PATH
                                       ).AndReturn(self.SIZE)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        self.assertRaises(exception.ImageTooLarge, image.create_image, None,
                          self.TEMPLATE_PATH, 1)
        self.mox.VerifyAll()

    def test_create_image_with_size_template_exists(self):
        fn = self.prepare_mocks()
        fn(target=self.TEMPLATE_PATH)
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(imagebackend.disk, 'get_disk_size')
        os.path.exists(self.QCOW2_BASE).AndReturn(True)
        imagebackend.disk.get_disk_size(self.TEMPLATE_PATH
                                       ).AndReturn(self.SIZE)
        imagebackend.libvirt_utils.create_cow_image(self.QCOW2_BASE,
                                                    self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

        self.mox.VerifyAll()


class LvmTestCase(_ImageTestCase):
    VG = 'FakeVG'
    TEMPLATE_SIZE = 512
    SIZE = 1024

    def setUp(self):
        self.image_class = imagebackend.Lvm
        super(LvmTestCase, self).setUp()
        self.flags(libvirt_images_volume_group=self.VG)
        self.LV = '%s_%s' % (self.INSTANCE, self.NAME)
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
        fn(target=self.TEMPLATE_PATH)
        self.libvirt_utils.create_lvm_image(self.VG,
                                            self.LV,
                                            self.TEMPLATE_SIZE,
                                            sparse=sparse)
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        cmd = ('dd', 'if=%s' % self.TEMPLATE_PATH,
               'of=%s' % self.PATH, 'bs=4M')
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
        fn(target=self.TEMPLATE_PATH)
        self.libvirt_utils.create_lvm_image(self.VG, self.LV,
                                            self.SIZE, sparse=sparse)
        self.disk.get_disk_size(self.TEMPLATE_PATH
                                         ).AndReturn(self.TEMPLATE_SIZE)
        cmd = ('dd', 'if=%s' % self.TEMPLATE_PATH,
               'of=%s' % self.PATH, 'bs=4M')
        self.utils.execute(*cmd, run_as_root=True)
        self.disk.resize2fs(self.PATH)
        self.mox.ReplayAll()

        image = self.image_class(self.INSTANCE, self.NAME)
        image.create_image(fn, self.TEMPLATE_PATH, self.SIZE)

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
        fn(target=self.TEMPLATE_PATH)
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


class BackendTestCase(test.TestCase):
    INSTANCE = 'fake-instance'
    NAME = 'fake-name.suffix'

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

    def test_image_default(self):
        self._test_image('default', imagebackend.Raw, imagebackend.Qcow2)
