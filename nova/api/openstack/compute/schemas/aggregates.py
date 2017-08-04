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

availability_zone = {'oneOf': [parameter_types.az_name, {'type': 'null'}]}
availability_zone_with_leading_trailing_spaces = {
    'oneOf': [parameter_types.az_name_with_leading_trailing_spaces,
              {'type': 'null'}]
}


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


create_v20 = copy.deepcopy(create)
create_v20['properties']['aggregate']['properties']['name'] = (parameter_types.
    name_with_leading_trailing_spaces)
create_v20['properties']['aggregate']['properties']['availability_zone'] = (
    availability_zone_with_leading_trailing_spaces)


update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'aggregate': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_with_leading_trailing_spaces,
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


update_v20 = copy.deepcopy(update)
update_v20['properties']['aggregate']['properties']['name'] = (parameter_types.
    name_with_leading_trailing_spaces)
update_v20['properties']['aggregate']['properties']['availability_zone'] = (
    availability_zone_with_leading_trailing_spaces)


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
