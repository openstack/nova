# Copyright 2016 OpenStack Foundation
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

import copy

from nova.api.validation import parameter_types


force_complete = {
    'type': 'object',
    'properties': {
        'force_complete': {
            'type': 'null'
        }
    },
    'required': ['force_complete'],
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

force_complete_response = {
    'type': 'null',
}

_migration_response = {
    'type': 'object',
    'properties': {
        'created_at': {'type': 'string', 'format': 'date-time'},
        'dest_compute': {'type': ['string', 'null']},
        'dest_host': {'type': ['string', 'null']},
        'dest_node': {'type': ['string', 'null']},
        'disk_processed_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'disk_remaining_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'disk_total_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'id': {'type': 'integer'},
        'memory_processed_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'memory_remaining_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'memory_total_bytes': {'type': ['integer', 'null'], 'minimum': 1},
        'server_uuid': {'type': 'string', 'format': 'uuid'},
        'source_compute': {'type': ['string', 'null']},
        'source_node': {'type': ['string', 'null']},
        'status': {'type': 'string'},
        'updated_at': {'type': 'string', 'format': 'date-time'},
    },
    'required': [
        'created_at',
        'dest_compute',
        'dest_host',
        'dest_node',
        'disk_processed_bytes',
        'disk_remaining_bytes',
        'disk_total_bytes',
        'id',
        'memory_processed_bytes',
        'memory_remaining_bytes',
        'memory_total_bytes',
        'server_uuid',
        'source_compute',
        'source_node',
        'status',
        'updated_at',
    ],
    'additionalProperties': False,
}

_migration_response_v259 = copy.deepcopy(_migration_response)
_migration_response_v259['properties'].update({
    'uuid': {'type': 'string', 'format': 'uuid'},
})
_migration_response_v259['required'].append('uuid')

_migration_response_v280 = copy.deepcopy(_migration_response_v259)
_migration_response_v280['properties'].update({
    'project_id': parameter_types.project_id,
    'user_id': parameter_types.user_id,
})
_migration_response_v280['required'].extend([
    'project_id', 'user_id'
])

index_response_v223 = {
    'type': 'object',
    'properties': {
        'migrations': {
            'type': 'array',
            'items': _migration_response,
        },
    },
    'required': ['migrations'],
    'additionalProperties': False,
}

index_response_v259 = copy.deepcopy(index_response_v223)
index_response_v259['properties']['migrations']['items'] = (
    _migration_response_v259
)

index_response_v280 = copy.deepcopy(index_response_v259)
index_response_v280['properties']['migrations']['items'] = (
    _migration_response_v280
)

show_response_v223 = {
    'type': 'object',
    'properties': {
        'migration': _migration_response,
    },
    'required': ['migration'],
    'additionalProperties': False,
}

show_response_v259 = copy.deepcopy(show_response_v223)
show_response_v259['properties']['migration'] = (
    _migration_response_v259
)

show_response_v280 = copy.deepcopy(show_response_v259)
show_response_v280['properties']['migration'] = (
    _migration_response_v280
)

delete_response_v224 = {'type': 'null'}
