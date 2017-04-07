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

"""The legacy block device mappings extension."""

from oslo_utils import strutils
from webob import exc

from nova.api.openstack.compute.schemas import block_device_mapping_v1 as \
    schema_block_device_mapping
from nova.api.openstack import extensions
from nova.i18n import _

ALIAS = "os-block-device-mapping-v1"
ATTRIBUTE_NAME = "block_device_mapping"
ATTRIBUTE_NAME_V2 = "block_device_mapping_v2"


class BlockDeviceMappingV1(extensions.V21APIExtensionBase):
    """Block device mapping boot support."""

    name = "BlockDeviceMappingV1"
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
def server_create(server_dict, create_kwargs, body_deprecated_param):
    block_device_mapping = server_dict.get(ATTRIBUTE_NAME, [])
    block_device_mapping_v2 = server_dict.get(ATTRIBUTE_NAME_V2, [])

    if block_device_mapping and block_device_mapping_v2:
        expl = _('Using different block_device_mapping syntaxes '
                 'is not allowed in the same request.')
        raise exc.HTTPBadRequest(explanation=expl)

    for bdm in block_device_mapping:
        if 'delete_on_termination' in bdm:
            bdm['delete_on_termination'] = strutils.bool_from_string(
                bdm['delete_on_termination'])

    if block_device_mapping:
        create_kwargs['block_device_mapping'] = block_device_mapping
        # Sets the legacy_bdm flag if we got a legacy block device mapping.
        create_kwargs['legacy_bdm'] = True


def get_server_create_schema(version):
    return schema_block_device_mapping.server_create
