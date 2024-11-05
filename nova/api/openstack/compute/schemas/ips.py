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

_ip_address = {
    'type': 'object',
    'properties': {
        'addr': {
            'type': 'string',
            'oneOf': [
                {'format': 'ipv4'},
                {'format': 'ipv6'},
            ],
        },
        'version': {
            'enum': [4, 6],
        },
    },
    'required': ['addr', 'version'],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        'addresses': {
            'type': 'object',
            'patternProperties': {
                # TODO(stephenfin): Surely there are some limitations on
                # network names?
                '^.+$': {
                    'type': 'array',
                    'items': copy.deepcopy(_ip_address),
                },
            },
        },
    },
    'required': ['addresses'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'patternProperties': {
        # TODO(stephenfin): Surely there are some limitations on
        # network names?
        '^.+$': {
            'type': 'array',
            'items': copy.deepcopy(_ip_address),
        },
    },
}
