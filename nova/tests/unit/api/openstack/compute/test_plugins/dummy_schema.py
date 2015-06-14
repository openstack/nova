# Copyright 2014 IBM
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

dummy = {
    'type': 'object',
    'properties': {
        'dummy': {
            'type': 'object',
            'properties': {
                'val': parameter_types.name,
            },
            'additionalProperties': False,
        },
    },
    'required': ['dummy'],
    'additionalProperties': False,
}

dummy2 = {
    'type': 'object',
    'properties': {
        'dummy': {
            'type': 'object',
            'properties': {
                'val2': parameter_types.name,
            },
            'additionalProperties': False,
        },
    },
    'required': ['dummy'],
    'additionalProperties': False,
}
