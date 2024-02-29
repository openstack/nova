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

_extension_obj = {
    'type': 'object',
    'properties': {
        'alias': {'type': 'string'},
        'description': {'type': 'string'},
        'links': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'href': {
                        'type': 'string',
                        'format': 'url'
                    },
                    'rel': {
                        'type': 'string'
                    },
                }
            },
        },
        'name': {'type': 'string'},
        'namespace': {'type': 'string'},
        'updated': {'type': 'string', 'format': 'date-time'},
    },
    'required': [
        'alias', 'description', 'links', 'name', 'namespace', 'updated'
    ],
    'additionalProperties': False,
}


index_response = {
    'type': 'object',
    'properties': {
        'extensions': {
            'type': 'array',
            'items': _extension_obj,
        }
    },
    'required': ['extensions'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'extension': _extension_obj,
    },
    'required': ['extension'],
    'additionalProperties': False,
}
