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

from nova.api.validation import parameter_types

legacy_block_device_mapping = {
    'type': 'object',
    'properties': {
        'virtual_name': {
            'type': 'string', 'maxLength': 255,
        },
        'volume_id': parameter_types.volume_id,
        'snapshot_id': parameter_types.image_id,
        'volume_size': parameter_types.volume_size,
        # Do not allow empty device names and number values and
        # containing spaces(defined in nova/block_device.py:from_api())
        'device_name': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
            'pattern': '^[a-zA-Z0-9._-r/]*$',
        },
        # Defined as boolean in nova/block_device.py:from_api()
        'delete_on_termination': parameter_types.boolean,
        'no_device': {},
        # Defined as mediumtext in column "connection_info" in table
        # "block_device_mapping"
        'connection_info': {
            'type': 'string', 'maxLength': 16777215
        },
    },
    'additionalProperties': False
}

server_create = {
    'block_device_mapping': {
        'type': 'array',
        'items': legacy_block_device_mapping
    }
}
