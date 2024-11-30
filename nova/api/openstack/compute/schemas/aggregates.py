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

_availability_zone = {'oneOf': [parameter_types.az_name, {'type': 'null'}]}
_availability_zone_with_leading_trailing_spaces = {
    'oneOf': [parameter_types.az_name_with_leading_trailing_spaces,
              {'type': 'null'}]
}

create = {
    'type': 'object',
    'properties': {
        'aggregate': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'availability_zone': _availability_zone,
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['aggregate'],
    'additionalProperties': False,
}


create_v20 = copy.deepcopy(create)
create_v20['properties']['aggregate']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces)
create_v20['properties']['aggregate']['properties']['availability_zone'] = (
    _availability_zone_with_leading_trailing_spaces)


update = {
    'type': 'object',
    'properties': {
        'aggregate': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_with_leading_trailing_spaces,
                'availability_zone': _availability_zone
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
update_v20['properties']['aggregate']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces)
update_v20['properties']['aggregate']['properties']['availability_zone'] = (
    _availability_zone_with_leading_trailing_spaces)


add_host = {
    'type': 'object',
    'properties': {
        'add_host': {
            'type': 'object',
            'properties': {
                'host': parameter_types.fqdn,
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
        'remove_host': {
            'type': 'object',
            'properties': {
                'host': parameter_types.fqdn,
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

# TODO(stephenfin): Remove additionalProperties in a future API version
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_aggregate_response = {
    'type': 'object',
    'properties': {
        'aggregate': {
            'type': 'object',
            'properties': {
                'availability_zone': {'type': ['null', 'string']},
                'created_at': {'type': 'string', 'format': 'date-time'},
                'deleted': {'type': 'boolean'},
                'deleted_at': {
                    'oneOf': [
                        {'type': 'null'},
                        {'type': 'string', 'format': 'date-time'},
                    ],
                },
                'hosts': {
                    'type': ['array', 'null'],
                    'items': {
                        'type': 'string',
                    },
                },
                'id': {'type': 'integer'},
                # TODO(stephenfin): This should be stricter
                'metadata': {
                    'type': ['null', 'object'],
                    'properties': {},
                    'additionalProperties': True,
                },
                'name': {'type': 'string'},
                'updated_at': {
                    'oneOf': [
                        {'type': 'null'},
                        {'type': 'string', 'format': 'date-time'},
                    ],
                },
            },
            'required': [
                'availability_zone',
                'created_at',
                'deleted',
                'deleted_at',
                'hosts',
                'id',
                'metadata',
                'name',
                'updated_at',
            ],
            'additionalProperties': False,
        },
    },
    'required': ['aggregate'],
    'additionalProperties': False,
}

_aggregate_response_v241 = copy.deepcopy(_aggregate_response)
_aggregate_response_v241['properties']['aggregate']['properties'].update(
    {'uuid': {'type': 'string', 'format': 'uuid'}},
)
_aggregate_response_v241['properties']['aggregate']['required'].append('uuid')

add_host_response = copy.deepcopy(_aggregate_response)
add_host_response_v241 = copy.deepcopy(_aggregate_response_v241)

remove_host_response = copy.deepcopy(_aggregate_response)
remove_host_response_v241 = copy.deepcopy(_aggregate_response_v241)

set_metadata_response = copy.deepcopy(_aggregate_response)
set_metadata_response_v241 = copy.deepcopy(_aggregate_response_v241)
