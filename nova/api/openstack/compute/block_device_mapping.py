# Copyright 2013 OpenStack Foundation
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

"""The block device mappings extension."""

from webob import exc

from nova.api.openstack.compute.schemas import block_device_mapping as \
                                                  schema_block_device_mapping
from nova.api.openstack import extensions
from nova import block_device
from nova import exception
from nova.i18n import _

ALIAS = "os-block-device-mapping"
ATTRIBUTE_NAME = "block_device_mapping_v2"
LEGACY_ATTRIBUTE_NAME = "block_device_mapping"


class BlockDeviceMapping(extensions.V21APIExtensionBase):
    """Block device mapping boot support."""

    name = "BlockDeviceMapping"
    alias = ALIAS
    version = 1

    def get_resources(self):
        return []

    def get_controller_extensions(self):
        return []

    # use nova.api.extensions.server.extensions entry point to modify
    # server create kwargs
    # NOTE(gmann): This function is not supposed to use 'body_deprecated_param'
    # parameter as this is placed to handle scheduler_hint extension for V2.1.
    def server_create(self, server_dict, create_kwargs, body_deprecated_param):

        # Have to check whether --image is given, see bug 1433609
        image_href = server_dict.get('imageRef')
        image_uuid_specified = image_href is not None

        bdm = server_dict.get(ATTRIBUTE_NAME, [])
        legacy_bdm = server_dict.get(LEGACY_ATTRIBUTE_NAME, [])

        if bdm and legacy_bdm:
            expl = _('Using different block_device_mapping syntaxes '
                     'is not allowed in the same request.')
            raise exc.HTTPBadRequest(explanation=expl)

        try:
            block_device_mapping = [
                block_device.BlockDeviceDict.from_api(bdm_dict,
                    image_uuid_specified)
                for bdm_dict in bdm]
        except exception.InvalidBDMFormat as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if block_device_mapping:
            create_kwargs['block_device_mapping'] = block_device_mapping
            # Unset the legacy_bdm flag if we got a block device mapping.
            create_kwargs['legacy_bdm'] = False

    def get_server_create_schema(self, version):
        return schema_block_device_mapping.server_create
