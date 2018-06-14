# Copyright 2017 Citrix Systems
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

""" This class will stream image data directly between glance and VDI.
"""

from os_xenapi.client import exception as xenapi_exception
from os_xenapi.client import image as xenapi_image
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova import image
from nova import utils as nova_utils
from nova.virt.xenapi.image import utils
from nova.virt.xenapi import vm_utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

IMAGE_API = image.API()


class VdiStreamStore(object):
    def download_image(self, context, session, instance, image_id):
        try:
            host_url = CONF.xenserver.connection_url
            image_data = IMAGE_API.download(context, image_id)
            image_stream = utils.IterableToFileAdapter(image_data)
            sr_ref = vm_utils.safe_find_sr(session)
            vdis = xenapi_image.stream_to_vdis(context, session,
                                               instance, host_url,
                                               sr_ref, image_stream)
        except xenapi_exception.OsXenApiException as e:
            LOG.error("Image download failed with exception: %s", e)
            raise exception.CouldNotFetchImage(image_id=image_id)
        return vdis

    def _get_metadata(self, context, instance, image_id):
        metadata = IMAGE_API.get(context, image_id)
        metadata['disk_format'] = 'vhd'
        metadata['container_format'] = 'ovf'
        metadata['auto_disk_config'] = str(instance['auto_disk_config'])
        metadata['os_type'] = instance.get('os_type') or (
            CONF.xenserver.default_os_type)
        # Set size as zero, so that it will update the size in the end
        # based on the uploaded image data.
        metadata['size'] = 0

        # Adjust the auto_disk_config value basing on instance's
        # system metadata.
        # TODO(mriedem): Consider adding an abstract base class for the
        # various image handlers to contain common code like this.
        auto_disk = nova_utils.get_auto_disk_config_from_instance(instance)
        if nova_utils.is_auto_disk_config_disabled(auto_disk):
            metadata['auto_disk_config'] = "disabled"

        return metadata

    def upload_image(self, context, session, instance, image_id, vdi_uuids):
        try:
            host_url = CONF.xenserver.connection_url
            level = vm_utils.get_compression_level()
            metadata = self._get_metadata(context, instance, image_id)
            image_chunks = xenapi_image.stream_from_vdis(
                context, session, instance, host_url, vdi_uuids,
                compresslevel=level)
            image_stream = utils.IterableToFileAdapter(image_chunks)
            IMAGE_API.update(context, image_id, metadata,
                             data=image_stream)
        except xenapi_exception.OsXenApiException as e:
            LOG.error("Image upload failed with exception: %s", e)
            raise exception.CouldNotUploadImage(image_id=image_id)
