# Copyright 2013 NEC Corporation.  All rights reserved.
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
from nova.api.validation import response_types


create = {
    'type': 'object',
    'properties': {
        'keypair': {
            'type': 'object',
            'properties': {
                'name': parameter_types.keypair_name_special_chars,
                'public_key': {'type': 'string'},
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['keypair'],
    'additionalProperties': False,
}


create_v20 = copy.deepcopy(create)
create_v20['properties']['keypair']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces)


create_v22 = {
    'type': 'object',
    'properties': {
        'keypair': {
            'type': 'object',
            'properties': {
                'name': parameter_types.keypair_name_special_chars,
                'type': {
                    'type': 'string',
                    'enum': ['ssh', 'x509']
                },
                'public_key': {'type': 'string'},
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['keypair'],
    'additionalProperties': False,
}

create_v210 = {
    'type': 'object',
    'properties': {
        'keypair': {
            'type': 'object',
            'properties': {
                'name': parameter_types.keypair_name_special_chars,
                'type': {
                    'type': 'string',
                    'enum': ['ssh', 'x509']
                },
                'public_key': {'type': 'string'},
                'user_id': {'type': 'string'},
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['keypair'],
    'additionalProperties': False,
}

create_v292 = copy.deepcopy(create_v210)
create_v292['properties']['keypair']['properties']['name'] = (
    parameter_types.keypair_name_special_chars_v292)
create_v292['properties']['keypair']['required'] = ['name', 'public_key']

index_query_schema_v20 = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True
}

index_query_schema_v210 = {
    'type': 'object',
    'properties': {
        'user_id': parameter_types.multi_params({'type': 'string'})
    },
    'additionalProperties': True
}

index_query_schema_v235 = copy.deepcopy(index_query_schema_v210)
index_query_schema_v235['properties'].update(
    parameter_types.pagination_parameters)

show_query_schema_v20 = index_query_schema_v20
show_query_schema_v210 = index_query_schema_v210
delete_query_schema_v20 = index_query_schema_v20
delete_query_schema_v210 = index_query_schema_v210

index_query_schema_v275 = copy.deepcopy(index_query_schema_v235)
index_query_schema_v275['additionalProperties'] = False
show_query_schema_v275 = copy.deepcopy(show_query_schema_v210)
show_query_schema_v275['additionalProperties'] = False
delete_query_schema_v275 = copy.deepcopy(delete_query_schema_v210)
delete_query_schema_v275['additionalProperties'] = False

create_response = {
    'type': 'object',
    'properties': {
        'keypair': {
            'type': 'object',
            'properties': {
                'fingerprint': {'type': 'string'},
                'name': parameter_types.keypair_name_special_chars,
                'private_key': {'type': 'string'},
                'public_key': {'type': 'string'},
                'user_id': parameter_types.user_id,
            },
            'required': ['fingerprint', 'name', 'public_key', 'user_id'],
            'additionalProperties': False,
        }
    },
    'required': ['keypair'],
    'additionalProperties': False,
}

create_response_v22 = copy.deepcopy(create_response)
create_response_v22['properties']['keypair']['properties'].update({
    'type': {
        'type': 'string',
        'enum': ['ssh', 'x509']
    },
})
create_response_v22['properties']['keypair']['required'].append('type')

create_response_v292 = copy.deepcopy(create_response_v22)
del create_response_v292['properties']['keypair']['properties']['private_key']
create_response_v292['properties']['keypair']['properties']['name'] = (
    parameter_types.keypair_name_special_chars_v292
)

delete_response = {
    'type': 'null',
}

show_response = {
    'type': 'object',
    'properties': {
        'keypair': {
            'type': 'object',
            'properties': {
                'created_at': {'type': 'string', 'format': 'date-time'},
                'deleted': {'type': 'boolean'},
                'deleted_at': {
                    'oneOf': [
                        {'type': 'string', 'format': 'date-time'},
                        {'type': 'null'},
                    ],
                },
                'fingerprint': {'type': 'string'},
                'id': {'type': 'integer'},
                'name': parameter_types.keypair_name_special_chars,
                'public_key': {'type': 'string'},
                'updated_at': {
                    'oneOf': [
                        {'type': 'string', 'format': 'date-time'},
                        {'type': 'null'},
                    ],
                },
                'user_id': parameter_types.user_id,
            },
            'required': [
                'created_at',
                'deleted',
                'deleted_at',
                'fingerprint',
                'id',
                'name',
                'public_key',
                'updated_at',
                'user_id'
            ],
            'additionalProperties': False,
        }
    },
    'required': ['keypair'],
    'additionalProperties': False,
}

show_response_v22 = copy.deepcopy(show_response)
show_response_v22['properties']['keypair']['properties'].update({
    'type': {
        'type': 'string',
        'enum': ['ssh', 'x509']
    },
})
show_response_v22['properties']['keypair']['required'].append('type')

index_response = {
    'type': 'object',
    'properties': {
        'keypairs': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'keypair': {
                        'type': 'object',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'fingerprint': {'type': 'string'},
                                'name': parameter_types.keypair_name_special_chars,  # noqa: E501
                                'public_key': {'type': 'string'},
                            },
                            'required': ['fingerprint', 'name', 'public_key'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['keypair'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['keypairs'],
    'additionalProperties': False,
}

index_response_v22 = copy.deepcopy(index_response)
index_response_v22['properties']['keypairs']['items']['properties'][
    'keypair'
]['items']['properties'].update({
    'type': {
        'type': 'string',
        'enum': ['ssh', 'x509']
    },
})
index_response_v22['properties']['keypairs']['items']['properties'][
    'keypair'
]['items']['required'].append(
    'type'
)

index_response_v235 = copy.deepcopy(index_response_v22)
index_response_v235['properties'].update({
    'keypairs_links': response_types.collection_links,
})
