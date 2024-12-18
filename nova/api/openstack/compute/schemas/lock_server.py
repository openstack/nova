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

lock = {
    'type': 'object',
    'properties': {
        'lock': {},
    },
    'required': ['lock'],
    'additionalProperties': False,
}

lock_v273 = {
    'type': 'object',
    'properties': {
        'lock': {
            'type': ['object', 'null'],
            'properties': {
                'locked_reason': {
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'additionalProperties': False,
        },
    },
    'required': ['lock'],
    'additionalProperties': False,
}

# TODO(stephenfin): Restrict the value to 'null' in a future API version
unlock = {
    'type': 'object',
    'properties': {
        'unlock': {},
    },
    'required': ['unlock'],
    'additionalProperties': False,
}

lock_response = {
    'type': 'null',
}

unlock_response = {
    'type': 'null',
}
