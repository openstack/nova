# Copyright 2017 Huawei Technologies Co.,LTD.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from nova.api.validation import parameter_types
from nova.api.validation import response_types

index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_query_v258 = {
    'type': 'object',
    'properties': {
        # The 2.58 microversion added support for paging by limit and marker
        # and filtering by changes-since.
        'limit': parameter_types.single_param(
            parameter_types.non_negative_integer),
        'marker': parameter_types.single_param({'type': 'string'}),
        'changes-since': parameter_types.single_param(
            {'type': 'string', 'format': 'date-time'}),
    },
    'additionalProperties': False
}

index_query_v266 = copy.deepcopy(index_query_v258)
index_query_v266['properties'].update({
    'changes-before': parameter_types.single_param(
            {'type': 'string', 'format': 'date-time'}),
})

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_response = {
    'type': 'object',
    'properties': {
        'instanceActions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'action': {'type': 'string'},
                    'instance_uuid': {'type': 'string', 'format': 'uuid'},
                    'message': {'type': ['null', 'string']},
                    # NOTE(stephenfin): While this will always be set for
                    # API-initiated actions, it will not be set for e.g.
                    # `nova-manage`-initiated actions
                    'project_id': {
                        'type': ['null', 'string'],
                        'pattern': '^[a-zA-Z0-9-]*$',
                        'minLength': 1,
                        'maxLength': 255,
                    },
                    'request_id': {'type': 'string'},
                    'start_time': {'type': 'string', 'format': 'date-time'},
                    # NOTE(stephenfin): As with project_id, this can be null
                    # under select circumstances.
                    'user_id': {
                        'type': ['null', 'string'],
                        'pattern': '^[a-zA-Z0-9-]*$',
                        'minLength': 1,
                        'maxLength': 255,
                    },
                },
                'required': [
                    'action',
                    'instance_uuid',
                    'message',
                    'project_id',
                    'request_id',
                    'start_time',
                    'user_id',
                ],
                'additionalProperties': False,
            },
        },
    },
    'required': ['instanceActions'],
    'additionalProperties': False,
}

index_response_v258 = copy.deepcopy(index_response)
index_response_v258['properties']['instanceActions']['items'][
    'properties'
].update({
    'updated_at': {'type': ['null', 'string'], 'format': 'date-time'},
})
index_response_v258['properties']['instanceActions']['items'][
    'required'
].append('updated_at')
index_response_v258['properties']['links'] = response_types.collection_links

show_response = {
    'type': 'object',
    'properties': {
        'instanceAction': {
            'type': 'object',
            'properties': {
                'action': {'type': 'string'},
                'instance_uuid': {'type': 'string', 'format': 'uuid'},
                'events': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'event': {'type': 'string'},
                            'finish_time': {
                                'type': ['string', 'null'],
                                'format': 'date-time',
                            },
                            'result': {'type': ['string', 'null']},
                            'start_time': {
                                'type': 'string', 'format': 'date-time',
                            },
                            'traceback': {'type': ['null', 'string']},
                        },
                        'required': [
                            'event',
                            'finish_time',
                            'result',
                            'start_time',
                        ],
                        'additionalProperties': False,
                    },
                },
                'message': {'type': ['null', 'string']},
                'project_id': {
                    'type': ['null', 'string'],
                    'pattern': '^[a-zA-Z0-9-]*$',
                    'minLength': 1,
                    'maxLength': 255,
                },
                'request_id': {'type': 'string'},
                'start_time': {'type': 'string', 'format': 'date-time'},
                'user_id': {
                    'type': ['null', 'string'],
                    'pattern': '^[a-zA-Z0-9-]*$',
                    'minLength': 1,
                    'maxLength': 255,
                },
            },
            'required': [
                'action',
                'instance_uuid',
                'message',
                'project_id',
                'request_id',
                'start_time',
                'user_id',
            ],
            'additionalProperties': False,
        },
    },
    'required': ['instanceAction'],
    'additionalProperties': False,
}

show_response_v251 = copy.deepcopy(show_response)
show_response_v251['properties']['instanceAction']['required'].append(
    'events'
)

show_response_v258 = copy.deepcopy(show_response_v251)
show_response_v258['properties']['instanceAction']['properties'].update({
    'updated_at': {'type': ['null', 'string'], 'format': 'date-time'},
})
show_response_v258['properties']['instanceAction']['required'].append(
    'updated_at'
)

show_response_v262 = copy.deepcopy(show_response_v258)
show_response_v262['properties']['instanceAction']['properties']['events'][
    'items'
]['properties'].update({
    'hostId': {'type': 'string'},
    'host': {'type': 'string'},
})
show_response_v262['properties']['instanceAction']['properties']['events'][
    'items'
]['required'].append('hostId')

show_response_v284 = copy.deepcopy(show_response_v262)
show_response_v284['properties']['instanceAction']['properties']['events'][
    'items'
]['properties'].update({
    'details': {'type': ['string', 'null']},
})
