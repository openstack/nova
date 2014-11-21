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

from nova.api.validation import parameter_types

availability_zone = copy.deepcopy(parameter_types.name)
availability_zone['type'] = ['string', 'null']

create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'aggregate': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'availability_zone': availability_zone,
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['aggregate'],
    'additionalProperties': False,
}

update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'aggregate': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'availability_zone': availability_zone
            },
            'additionalProperties': False,
            'anyOf': [
                {'required': ['name']},
                {'required': ['availability_zone']}
            ]
        },
    },
    'required': ['aggregate'],
    'additionalProperties': False,
}

add_host = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'add_host': {
            'type': 'object',
            'properties': {
                'host': parameter_types.hostname,
            },
            'required': ['host'],
            'additionalProperties': False,
        },
    },
    'required': ['add_host'],
    'additionalProperties': False,
}

remove_host = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'remove_host': {
            'type': 'object',
            'properties': {
                'host': parameter_types.hostname,
            },
            'required': ['host'],
            'additionalProperties': False,
        },
    },
    'required': ['remove_host'],
    'additionalProperties': False,
}


set_metadata = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'set_metadata': {
            'type': 'object',
            'properties': {
                'metadata': parameter_types.metadata_with_null
            },
            'required': ['metadata'],
            'additionalProperties': False,
        },
    },
    'required': ['set_metadata'],
    'additionalProperties': False,
}
