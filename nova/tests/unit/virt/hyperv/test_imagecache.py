# Copyright 2014 Cloudbase Solutions Srl
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

import mock
from oslo_config import cfg
from oslo_utils import units

from nova import exception
from nova import objects
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_flavor
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import imagecache

CONF = cfg.CONF


class ImageCacheTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V ImageCache class."""

    FAKE_BASE_DIR = 'fake/base/dir'
    FAKE_FORMAT = 'fake_format'
    FAKE_IMAGE_REF = 'fake_image_ref'
    FAKE_VHD_SIZE_GB = 1

    def setUp(self):
        super(ImageCacheTestCase, self).setUp()

        self.context = 'fake-context'
        self.instance = fake_instance.fake_instance_obj(self.context)

        # utilsfactory will check the host OS version via get_hostutils,
        # in order to return the proper Utils Class, so it must be mocked.
        patched_get_hostutils = mock.patch.object(imagecache.utilsfactory,
                                                  "get_hostutils")
        patched_get_vhdutils = mock.patch.object(imagecache.utilsfactory,
                                                 "get_vhdutils")
        patched_get_hostutils.start()
        patched_get_vhdutils.start()

        self.addCleanup(patched_get_hostutils.stop)
        self.addCleanup(patched_get_vhdutils.stop)

        self.imagecache = imagecache.ImageCache()
        self.imagecache._pathutils = mock.MagicMock()
        self.imagecache._vhdutils = mock.MagicMock()

    def _test_get_root_vhd_size_gb(self, old_flavor=True):
        if old_flavor:
            mock_flavor = objects.Flavor(**test_flavor.fake_flavor)
            self.instance.old_flavor = mock_flavor
        else:
            self.instance.old_flavor = None
        return self.imagecache._get_root_vhd_size_gb(self.instance)

    def test_get_root_vhd_size_gb_old_flavor(self):
        ret_val = self._test_get_root_vhd_size_gb()
        self.assertEqual(test_flavor.fake_flavor['root_gb'], ret_val)

    def test_get_root_vhd_size_gb(self):
        ret_val = self._test_get_root_vhd_size_gb(old_flavor=False)
        self.assertEqual(self.instance.root_gb, ret_val)

    @mock.patch.object(imagecache.ImageCache, '_get_root_vhd_size_gb')
    def test_resize_and_cache_vhd_smaller(self, mock_get_vhd_size_gb):
        self.imagecache._vhdutils.get_vhd_size.return_value = {
            'VirtualSize': (self.FAKE_VHD_SIZE_GB + 1) * units.Gi
        }
        mock_get_vhd_size_gb.return_value = self.FAKE_VHD_SIZE_GB
        mock_internal_vhd_size = (
            self.imagecache._vhdutils.get_internal_vhd_size_by_file_size)
        mock_internal_vhd_size.return_value = self.FAKE_VHD_SIZE_GB * units.Gi

        self.assertRaises(exception.FlavorDiskSmallerThanImage,
                          self.imagecache._resize_and_cache_vhd,
                          mock.sentinel.instance,
                          mock.sentinel.vhd_path)

        self.imagecache._vhdutils.get_vhd_size.assert_called_once_with(
            mock.sentinel.vhd_path)
        mock_get_vhd_size_gb.assert_called_once_with(mock.sentinel.instance)
        mock_internal_vhd_size.assert_called_once_with(
            mock.sentinel.vhd_path, self.FAKE_VHD_SIZE_GB * units.Gi)

    def _prepare_get_cached_image(self, path_exists, use_cow):
        self.instance.image_ref = self.FAKE_IMAGE_REF
        self.imagecache._pathutils.get_base_vhd_dir.return_value = (
            self.FAKE_BASE_DIR)
        self.imagecache._pathutils.exists.return_value = path_exists
        self.imagecache._vhdutils.get_vhd_format.return_value = (
            constants.DISK_FORMAT_VHD)

        CONF.set_override('use_cow_images', use_cow)

        expected_path = os.path.join(self.FAKE_BASE_DIR,
                                     self.FAKE_IMAGE_REF)
        expected_vhd_path = "%s.%s" % (expected_path,
                                       constants.DISK_FORMAT_VHD.lower())
        return (expected_path, expected_vhd_path)

    @mock.patch.object(imagecache.images, 'fetch')
    def test_get_cached_image_with_fetch(self, mock_fetch):
        (expected_path,
         expected_vhd_path) = self._prepare_get_cached_image(False, False)

        result = self.imagecache.get_cached_image(self.context, self.instance)
        self.assertEqual(expected_vhd_path, result)

        mock_fetch.assert_called_once_with(self.context, self.FAKE_IMAGE_REF,
                                           expected_path,
                                           self.instance['user_id'],
                                           self.instance['project_id'])
        self.imagecache._vhdutils.get_vhd_format.assert_called_once_with(
            expected_path)
        self.imagecache._pathutils.rename.assert_called_once_with(
            expected_path, expected_vhd_path)

    @mock.patch.object(imagecache.images, 'fetch')
    def test_get_cached_image_with_fetch_exception(self, mock_fetch):
        (expected_path,
         expected_vhd_path) = self._prepare_get_cached_image(False, False)

        # path doesn't exist until fetched.
        self.imagecache._pathutils.exists.side_effect = [False, False, True]
        mock_fetch.side_effect = exception.InvalidImageRef(
            image_href=self.FAKE_IMAGE_REF)

        self.assertRaises(exception.InvalidImageRef,
                          self.imagecache.get_cached_image,
                          self.context, self.instance)

        self.imagecache._pathutils.remove.assert_called_once_with(
            expected_path)

    @mock.patch.object(imagecache.ImageCache, '_resize_and_cache_vhd')
    def test_get_cached_image_use_cow(self, mock_resize):
        (expected_path,
         expected_vhd_path) = self._prepare_get_cached_image(True, True)

        expected_resized_vhd_path = expected_vhd_path + 'x'
        mock_resize.return_value = expected_resized_vhd_path

        result = self.imagecache.get_cached_image(self.context, self.instance)
        self.assertEqual(expected_resized_vhd_path, result)

        mock_resize.assert_called_once_with(self.instance, expected_vhd_path)
