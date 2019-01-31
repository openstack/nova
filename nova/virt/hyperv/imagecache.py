# Copyright 2013 Cloudbase Solutions Srl
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
"""
Image caching and management.
"""
import os
import re

from os_win import utilsfactory
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
from oslo_utils import uuidutils

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt.hyperv import pathutils
from nova.virt import imagecache
from nova.virt import images

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class ImageCache(imagecache.ImageCacheManager):
    def __init__(self):
        super(ImageCache, self).__init__()
        self._pathutils = pathutils.PathUtils()
        self._vhdutils = utilsfactory.get_vhdutils()

    def _get_root_vhd_size_gb(self, instance):
        if instance.old_flavor:
            return instance.old_flavor.root_gb
        else:
            return instance.flavor.root_gb

    def _resize_and_cache_vhd(self, instance, vhd_path):
        vhd_size = self._vhdutils.get_vhd_size(vhd_path)['VirtualSize']

        root_vhd_size_gb = self._get_root_vhd_size_gb(instance)
        root_vhd_size = root_vhd_size_gb * units.Gi

        root_vhd_internal_size = (
                self._vhdutils.get_internal_vhd_size_by_file_size(
                    vhd_path, root_vhd_size))

        if root_vhd_internal_size < vhd_size:
            raise exception.FlavorDiskSmallerThanImage(
                flavor_size=root_vhd_size, image_size=vhd_size)
        if root_vhd_internal_size > vhd_size:
            path_parts = os.path.splitext(vhd_path)
            resized_vhd_path = '%s_%s%s' % (path_parts[0],
                                            root_vhd_size_gb,
                                            path_parts[1])

            lock_path = os.path.dirname(resized_vhd_path)
            lock_name = "%s-cache.lock" % os.path.basename(resized_vhd_path)

            @utils.synchronized(name=lock_name, external=True,
                                lock_path=lock_path)
            def copy_and_resize_vhd():
                if not self._pathutils.exists(resized_vhd_path):
                    try:
                        LOG.debug("Copying VHD %(vhd_path)s to "
                                  "%(resized_vhd_path)s",
                                  {'vhd_path': vhd_path,
                                   'resized_vhd_path': resized_vhd_path})
                        self._pathutils.copyfile(vhd_path, resized_vhd_path)
                        LOG.debug("Resizing VHD %(resized_vhd_path)s to new "
                                  "size %(root_vhd_size)s",
                                  {'resized_vhd_path': resized_vhd_path,
                                   'root_vhd_size': root_vhd_size})
                        self._vhdutils.resize_vhd(resized_vhd_path,
                                                  root_vhd_internal_size,
                                                  is_file_max_size=False)
                    except Exception:
                        with excutils.save_and_reraise_exception():
                            if self._pathutils.exists(resized_vhd_path):
                                self._pathutils.remove(resized_vhd_path)

            copy_and_resize_vhd()
            return resized_vhd_path

    def get_cached_image(self, context, instance, rescue_image_id=None):
        image_id = rescue_image_id or instance.image_ref

        base_vhd_dir = self._pathutils.get_base_vhd_dir()
        base_vhd_path = os.path.join(base_vhd_dir, image_id)

        lock_name = "%s-cache.lock" % image_id

        @utils.synchronized(name=lock_name, external=True,
                            lock_path=base_vhd_dir)
        def fetch_image_if_not_existing():
            vhd_path = None
            for format_ext in ['vhd', 'vhdx']:
                test_path = base_vhd_path + '.' + format_ext
                if self._pathutils.exists(test_path):
                    vhd_path = test_path
                    break

            if not vhd_path:
                try:
                    images.fetch(context, image_id, base_vhd_path)

                    format_ext = self._vhdutils.get_vhd_format(base_vhd_path)
                    vhd_path = base_vhd_path + '.' + format_ext.lower()
                    self._pathutils.rename(base_vhd_path, vhd_path)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        if self._pathutils.exists(base_vhd_path):
                            self._pathutils.remove(base_vhd_path)

            return vhd_path

        vhd_path = fetch_image_if_not_existing()

        # Note: rescue images are not resized.
        is_vhd = vhd_path.split('.')[-1].lower() == 'vhd'
        if CONF.use_cow_images and is_vhd and not rescue_image_id:
            # Resize the base VHD image as it's not possible to resize a
            # differencing VHD. This does not apply to VHDX images.
            resized_vhd_path = self._resize_and_cache_vhd(instance, vhd_path)
            if resized_vhd_path:
                return resized_vhd_path

        if rescue_image_id:
            self._verify_rescue_image(instance, rescue_image_id,
                                      vhd_path)

        return vhd_path

    def _verify_rescue_image(self, instance, rescue_image_id,
                             rescue_image_path):
        rescue_image_info = self._vhdutils.get_vhd_info(rescue_image_path)
        rescue_image_size = rescue_image_info['VirtualSize']
        flavor_disk_size = instance.flavor.root_gb * units.Gi

        if rescue_image_size > flavor_disk_size:
            err_msg = _('Using a rescue image bigger than the instance '
                        'flavor disk size is not allowed. '
                        'Rescue image size: %(rescue_image_size)s. '
                        'Flavor disk size:%(flavor_disk_size)s.') % dict(
                            rescue_image_size=rescue_image_size,
                            flavor_disk_size=flavor_disk_size)
            raise exception.ImageUnacceptable(reason=err_msg,
                                              image_id=rescue_image_id)

    def get_image_details(self, context, instance):
        image_id = instance.image_ref
        return images.get_info(context, image_id)

    def _age_and_verify_cached_images(self, context, all_instances, base_dir):
        for img in self.originals:
            if img in self.used_images:
                # change the timestamp on the image so as to reflect the last
                # time it was used
                self._update_image_timestamp(img)
            elif CONF.remove_unused_base_images:
                self._remove_if_old_image(img)

    def _update_image_timestamp(self, image):
        backing_files = self._get_image_backing_files(image)
        for img in backing_files:
            os.utime(img, None)

    def _get_image_backing_files(self, image):
        base_file = self._pathutils.get_image_path(image)
        if not base_file:
            # not vhd or vhdx, ignore.
            return []

        backing_files = [base_file]
        resize_re = re.compile('%s_[0-9]+$' % image)
        for img in self.unexplained_images:
            match = resize_re.match(img)
            if match:
                backing_files.append(self._pathutils.get_image_path(img))

        return backing_files

    def _remove_if_old_image(self, image):
        backing_files = self._get_image_backing_files(image)
        max_age_seconds = CONF.remove_unused_original_minimum_age_seconds

        for img in backing_files:
            age_seconds = self._pathutils.get_age_of_file(img)
            if age_seconds > max_age_seconds:
                LOG.info("Removing old, unused image: %s", img)
                self._remove_old_image(img)

    def _remove_old_image(self, image_path):
        lock_path = os.path.dirname(image_path)
        lock_name = "%s-cache.lock" % os.path.basename(image_path)

        @utils.synchronized(name=lock_name, external=True,
                            lock_path=lock_path)
        def _image_synchronized_remove():
            self._pathutils.remove(image_path)

        _image_synchronized_remove()

    def update(self, context, all_instances):
        base_vhd_dir = self._pathutils.get_base_vhd_dir()

        running = self._list_running_instances(context, all_instances)
        self.used_images = running['used_images'].keys()
        all_files = self._list_base_images(base_vhd_dir)
        self.originals = all_files['originals']
        self.unexplained_images = all_files['unexplained_images']

        self._age_and_verify_cached_images(context, all_instances,
                                           base_vhd_dir)

    def _list_base_images(self, base_dir):
        unexplained_images = []
        originals = []

        for entry in os.listdir(base_dir):
            file_name, extension = os.path.splitext(entry)
            # extension has a leading '.'. E.g.: '.vhdx'
            if extension.lstrip('.').lower() not in ['vhd', 'vhdx']:
                # File is not an image. Ignore it.
                # imagecache will not store images of any other formats.
                continue

            if uuidutils.is_uuid_like(file_name):
                originals.append(file_name)
            else:
                unexplained_images.append(file_name)

        return {'unexplained_images': unexplained_images,
                'originals': originals}
