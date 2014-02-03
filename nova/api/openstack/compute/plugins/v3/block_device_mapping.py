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

from nova.api.openstack import extensions
from nova import block_device
from nova import exception

ALIAS = "os-block-device-mapping"
ATTRIBUTE_NAME = "%s:block_device_mapping" % ALIAS


class BlockDeviceMapping(extensions.V3APIExtensionBase):
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
    def server_create(self, server_dict, create_kwargs):
        block_device_mapping = server_dict.get(ATTRIBUTE_NAME, [])

        try:
            block_device_mapping = [
                block_device.BlockDeviceDict.from_api(bdm_dict)
                for bdm_dict in block_device_mapping]
        except exception.InvalidBDMFormat as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        create_kwargs['block_device_mapping'] = block_device_mapping

        # Unset the legacy_bdm flag if we got a block device mapping.
        if block_device_mapping:
            create_kwargs['legacy_bdm'] = False
