# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

# NOTE(stephenfin): These schemas are intentionally empty since these APIs are
# deprecated proxy APIs

create = {}
add_interface = {}
remove_interface = {}

index_query = {}
show_query = {}

_node = {
    'type': 'object',
    'properties': {
        'cpus': {'type': 'string'},
        'disk_gb': {'type': 'string'},
        'host': {'const': 'IRONIC MANAGED'},
        'id': {'type': 'string', 'format': 'uuid'},
        'interfaces': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'address': {'type': 'string'},
                },
            },
        },
        'memory_mb': {'type': 'string'},
        'task_state': {'type': 'string'},
    },
    'required': [
        'cpus',
        'disk_gb',
        'host',
        'id',
        'interfaces',
        'memory_mb',
        'task_state',
    ],
    'additionalProperties': False,
}
_node_detail = copy.deepcopy(_node)
_node_detail['properties']['instance_uuid'] = {
    'type': 'string', 'format': 'uuid'
}
_node_detail['required'].append('instance_uuid')

index_response = {
    'type': 'object',
    'properties': {
        'nodes': {
            'type': 'array',
            'items': copy.deepcopy(_node),
        },
    },
    'required': ['nodes'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'node': copy.deepcopy(_node_detail),
    },
    'required': ['node'],
    'additionalProperties': False,
}

create_response = {
    'type': 'null',
}

delete_response = {
    'type': 'null',
}

add_interface_response = {
    'type': 'null',
}

remove_interface_response = {
    'type': 'null',
}
