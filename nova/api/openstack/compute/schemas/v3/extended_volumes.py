# Copyright 2013 NEC Corporation.  All rights reserved.
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


swap_volume_attachment = {
    'type': 'object',
    'properties': {
        'swap_volume_attachment': {
            'type': 'object',
            'properties': {
                'old_volume_id': parameter_types.volume_id,
                'new_volume_id': parameter_types.volume_id
            },
            'required': ['old_volume_id', 'new_volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['swap_volume_attachment'],
    'additionalProperties': False,
}


attach = {
    'type': 'object',
    'properties': {
        'attach': {
            'type': 'object',
            'properties': {
                'volume_id': parameter_types.volume_id,
                'device': {
                    'type': 'string',
                    # NOTE: The validation pattern from match_device() in
                    #       nova/block_device.py.
                    'pattern': '(^/dev/x{0,1}[a-z]{0,1}d{0,1})([a-z]+)[0-9]*$'
                },
                'disk_bus': {
                    'type': 'string'
                },
                'device_type': {
                    'type': 'string',
                }
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['attach'],
    'additionalProperties': False,
}


detach = {
    'type': 'object',
    'properties': {
        'detach': {
            'type': 'object',
            'properties': {
                'volume_id': parameter_types.volume_id
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['detach'],
    'additionalProperties': False,
}
