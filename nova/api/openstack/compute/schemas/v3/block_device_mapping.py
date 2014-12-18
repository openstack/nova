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

server_create = {
    'block_device_mapping_v2': {
        'type': 'array',
        'items': [{
            'type': 'object',
            'properties': {
                'virtual_name': {
                    'type': 'string', 'maxLength': 255,
                },
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
                'volume_id': parameter_types.volume_id,
                'image_id': parameter_types.image_id,
                'snapshot_id': parameter_types.image_id,

                'volume_size': parameter_types.non_negative_integer,
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
        }]
    }
}
