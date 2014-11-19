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

from oslo.config import cfg
from oslo.utils import excutils
from oslo.utils import units

from nova.i18n import _
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vmutils
from nova.virt import images

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('use_cow_images', 'nova.virt.driver')


class ImageCache(object):
    def __init__(self):
        self._pathutils = utilsfactory.get_pathutils()
        self._vhdutils = utilsfactory.get_vhdutils()

    def _get_root_vhd_size_gb(self, instance):
        try:
            # In case of resizes we need the old root disk size
            old_flavor = instance.get_flavor('old')
            return old_flavor.root_gb
        except KeyError:
            return instance['root_gb']

    def _resize_and_cache_vhd(self, instance, vhd_path):
        vhd_info = self._vhdutils.get_vhd_info(vhd_path)
        vhd_size = vhd_info['MaxInternalSize']

        root_vhd_size_gb = self._get_root_vhd_size_gb(instance)
        root_vhd_size = root_vhd_size_gb * units.Gi

        root_vhd_internal_size = (
                self._vhdutils.get_internal_vhd_size_by_file_size(
                    vhd_path, root_vhd_size))

        if root_vhd_internal_size < vhd_size:
            raise vmutils.HyperVException(
                _("Cannot resize the image to a size smaller than the VHD "
                  "max. internal size: %(vhd_size)s. Requested disk size: "
                  "%(root_vhd_size)s") %
                {'vhd_size': vhd_size, 'root_vhd_size': root_vhd_size}
            )
        if root_vhd_internal_size > vhd_size:
            path_parts = os.path.splitext(vhd_path)
            resized_vhd_path = '%s_%s%s' % (path_parts[0],
                                            root_vhd_size_gb,
                                            path_parts[1])

            @utils.synchronized(resized_vhd_path)
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

    def get_cached_image(self, context, instance):
        image_id = instance['image_ref']

        base_vhd_dir = self._pathutils.get_base_vhd_dir()
        base_vhd_path = os.path.join(base_vhd_dir, image_id)

        @utils.synchronized(base_vhd_path)
        def fetch_image_if_not_existing():
            vhd_path = None
            for format_ext in ['vhd', 'vhdx']:
                test_path = base_vhd_path + '.' + format_ext
                if self._pathutils.exists(test_path):
                    vhd_path = test_path
                    break

            if not vhd_path:
                try:
                    images.fetch(context, image_id, base_vhd_path,
                                 instance['user_id'],
                                 instance['project_id'])

                    format_ext = self._vhdutils.get_vhd_format(base_vhd_path)
                    vhd_path = base_vhd_path + '.' + format_ext.lower()
                    self._pathutils.rename(base_vhd_path, vhd_path)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        if self._pathutils.exists(base_vhd_path):
                            self._pathutils.remove(base_vhd_path)

            return vhd_path

        vhd_path = fetch_image_if_not_existing()

        if CONF.use_cow_images and vhd_path.split('.')[-1].lower() == 'vhd':
            # Resize the base VHD image as it's not possible to resize a
            # differencing VHD. This does not apply to VHDX images.
            resized_vhd_path = self._resize_and_cache_vhd(instance, vhd_path)
            if resized_vhd_path:
                return resized_vhd_path

        return vhd_path
