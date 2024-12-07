# Copyright 2014 IBM Corporation.  All rights reserved.
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


# TODO(stephenfin): Remove additionalProperties in a future API version
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

detail_query = index_query

index_response = {
    'type': 'object',
    'properties': {
        'availabilityZoneInfo': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'hosts': {'type': 'null'},
                    'zoneName': {'type': 'string'},
                    'zoneState': {
                        'type': 'object',
                        'properties': {
                            'available': {'type': 'boolean'},
                        },
                    },
                },
                'required': ['hosts', 'zoneName', 'zoneState'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['availabilityZoneInfo'],
    'additionalProperties': False,
}

detail_response = copy.deepcopy(index_response)
detail_response['properties']['availabilityZoneInfo']['items']['properties']['hosts'] = {  # noqa: E501
    'type': ['null', 'object'],
    'patternProperties': {
        '^.+$': {
            'type': 'object',
            'patternProperties': {
                '^.+$': {
                    'type': 'object',
                    'properties': {
                        'active': {'type': 'boolean'},
                        'available': {'type': 'boolean'},
                        'updated_at': {
                            'oneOf': [
                                {'type': 'null'},
                                {'type': 'string', 'format': 'date-time'},
                            ],
                        },
                    },
                    'required': ['active', 'available', 'updated_at'],
                    'additionalProperties': False,
                },
            },
            'additionalProperties': False,
        },
    },
    'additionalProperties': False,
}
