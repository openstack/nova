# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.openstack.common import lockutils
from nova.openstack.common import log as logging
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt import images

LOG = logging.getLogger(__name__)


class ImageCache(object):
    def __init__(self):
        self._pathutils = pathutils.PathUtils()
        self._vhdutils = vhdutils.VHDUtils()

    def _validate_vhd_image(self, vhd_path):
        try:
            self._vhdutils.get_vhd_info(vhd_path)
        except Exception as ex:
            LOG.exception(ex)
            raise vmutils.HyperVException(_('The image is not a valid VHD: %s')
                                          % vhd_path)

    def get_cached_image(self, context, instance):
        image_id = instance['image_ref']

        base_vhd_dir = self._pathutils.get_base_vhd_dir()
        vhd_path = os.path.join(base_vhd_dir, image_id + ".vhd")

        @lockutils.synchronized(vhd_path, 'nova-')
        def fetch_image_if_not_existing():
            if not self._pathutils.exists(vhd_path):
                images.fetch(context, image_id, vhd_path,
                             instance['user_id'],
                             instance['project_id'])
                self._validate_vhd_image(vhd_path)

        fetch_image_if_not_existing()
        return vhd_path
