# Copyright 2014 NEC Corporation.  All rights reserved.
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

import copy

from nova.api.openstack.compute.schemas import block_device_mapping_v1
from nova.api.validation import parameter_types


block_device_mapping_new_item = {
    # defined in nova/block_device.py:from_api()
    # NOTE: Client can specify the Id with the combination of
    # source_type and uuid, or a single attribute like volume_id/
    # image_id/snapshot_id.
    'source_type': {
        'type': 'string',
        'enum': ['volume', 'image', 'snapshot', 'blank'],
    },
    'uuid': {
        'type': 'string', 'minLength': 1, 'maxLength': 255,
        'pattern': '^[a-zA-Z0-9._-]*$',
    },
    'image_id': parameter_types.image_id,
    # Defined as varchar(255) in column "destination_type" in table
    # "block_device_mapping"
    'destination_type': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as varchar(255) in column "guest_format" in table
    # "block_device_mapping"
    'guest_format': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as varchar(255) in column "device_type" in table
    # "block_device_mapping"
    'device_type': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as varchar(255) in column "disk_bus" in table
    # "block_device_mapping"
    'disk_bus': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as integer in nova/block_device.py:from_api()
    'boot_index': {
        'type': ['integer', 'string'],
        'pattern': '^-?[0-9]+$',
    },
}

block_device_mapping = copy.deepcopy(
                        block_device_mapping_v1.legacy_block_device_mapping)
block_device_mapping['properties'].update(block_device_mapping_new_item)

server_create = {
    'block_device_mapping_v2': {
        'type': 'array',
        'items': [block_device_mapping]
    }
}
