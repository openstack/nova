# Copyright 2014 IBM Corporation.  All rights reserved.
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

create = {
    'type': 'object',
    'properties': {
        'volume': {
            'type': 'object',
            'properties': {
                'volume_type': {'type': 'string'},
                'metadata': {'type': 'object'},
                'snapshot_id': {'type': 'string'},
                'size': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]+$',
                    'minimum': 1
                },
                'availability_zone': {'type': 'string'},
                'display_name': {'type': 'string'},
                'display_description': {'type': 'string'},
            },
            'additionalProperties': False,
        },
    },
    'required': ['volume'],
    'additionalProperties': False,
}


snapshot_create = {
    'type': 'object',
    'properties': {
        'snapshot': {
            'type': 'object',
            'properties': {
                'volume_id': {'type': 'string'},
                'force': parameter_types.boolean,
                'display_name': {'type': 'string'},
                'display_description': {'type': 'string'},
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['snapshot'],
    'additionalProperties': False,
}
