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

"""Common field types for validating API responses."""

links = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'rel': {
                'type': 'string',
                'enum': ['self', 'bookmark'],
            },
            'href': {
                'type': 'string',
                'format': 'uri',
            },
        },
        'required': ['rel', 'href'],
        'additionalProperties': False,
    },
}

collection_links = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'rel': {
                'const': 'next',
            },
            'href': {
                'type': 'string',
                'format': 'uri',
            },
        },
        'required': ['rel', 'href'],
        'additionalProperties': False,
    },
    # there should be one and only one link object
    'minItems': 1,
    'maxItems': 1,
}
