# Copyright 2014 NEC Corporation.  All rights reserved.
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

# NOTE(russellb) There is one other policy, 'legacy', but we don't allow that
# being set via the API.  It's only used when a group gets automatically
# created to support the legacy behavior of the 'group' scheduler hint.
create = {
    'type': 'object',
    'properties': {
        'server_group': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'policies': {
                    # This allows only a single item and it must be one of the
                    # enumerated values. It's changed to a single string value
                    # in 2.64.
                    'type': 'array',
                    'prefixItems': [
                        {
                            'type': 'string',
                            'enum': ['anti-affinity', 'affinity'],
                        },
                    ],
                    'uniqueItems': True,
                    'minItems': 1,
                    'maxItems': 1,
                    'additionalItems': False,
                }
            },
            'required': ['name', 'policies'],
            'additionalProperties': False,
        }
    },
    'required': ['server_group'],
    'additionalProperties': False,
}

create_v215 = copy.deepcopy(create)
policies = create_v215['properties']['server_group']['properties']['policies']
policies['prefixItems'][0]['enum'].extend(
    ['soft-anti-affinity', 'soft-affinity']
)

create_v264 = copy.deepcopy(create_v215)
del create_v264['properties']['server_group']['properties']['policies']
create_v264['properties']['server_group']['required'].remove('policies')
create_v264['properties']['server_group']['required'].append('policy')
create_v264['properties']['server_group']['properties']['policy'] = {
    'type': 'string',
    'enum': ['anti-affinity', 'affinity',
             'soft-anti-affinity', 'soft-affinity'],
}

create_v264['properties']['server_group']['properties']['rules'] = {
    'type': 'object',
    'properties': {
        'max_server_per_host':
            parameter_types.positive_integer,
    },
    'additionalProperties': False,
}

index_query = {
    'type': 'object',
    'properties': {
        'all_projects': parameter_types.multi_params({'type': 'string'}),
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'offset': parameter_types.multi_params(
             parameter_types.non_negative_integer),
    },
    # For backward compatible changes.  In microversion 2.75, we have
    # blocked the additional parameters.
    'additionalProperties': True
}

index_query_v275 = copy.deepcopy(index_query)
index_query_v275['additionalProperties'] = False

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_server_group_response = {
    'type': 'object',
    'properties': {
        'id': {'type': 'string', 'format': 'uuid'},
        'members': {
            'type': 'array',
            'items': {
                'type': 'string',
                'format': 'uuid',
            },
        },
        # Why yes, this is a **totally empty object**. It's removed later
        'metadata': {
            'type': 'object',
            'properties': {},
            'required': [],
            'additionalProperties': False,
        },
        'name': {'type': 'string'},
        'policies': {
            'type': 'array',
            'prefixItems': [
                {
                    'type': 'string',
                    'enum': ['affinity', 'anti-affinity',],
                },
            ],
            'minItems': 0,
            'maxItems': 1,
        },
    },
    'required': ['id', 'members', 'metadata', 'name', 'policies'],
    'additionalProperties': False,
}

_server_group_response_v213 = copy.deepcopy(_server_group_response)
_server_group_response_v213['properties'].update({
    'project_id': parameter_types.project_id,
    'user_id': parameter_types.user_id,
})
_server_group_response_v213['required'].extend(['project_id', 'user_id'])

_server_group_response_v215 = copy.deepcopy(_server_group_response_v213)
_server_group_response_v215['properties']['policies']['prefixItems'][0][
    'enum'
].extend(['soft-affinity', 'soft-anti-affinity'])

_server_group_response_v264 = copy.deepcopy(_server_group_response_v215)
del _server_group_response_v264['properties']['metadata']
del _server_group_response_v264['properties']['policies']
_server_group_response_v264['properties'].update({
    'policy': {
        'type': 'string',
        'enum': [
            'affinity',
            'anti-affinity',
            'soft-affinity',
            'soft-anti-affinity',
        ],
    },
    'rules': {
        'type': 'object',
        'properties': {
            'max_server_per_host': {'type': 'integer'},
        },
        'required': [],
        'additionalProperties': False,
    },
})
_server_group_response_v264['required'].remove('metadata')
_server_group_response_v264['required'].remove('policies')
_server_group_response_v264['required'].extend(['policy', 'rules'])

show_response = {
    'type': 'object',
    'properties': {
        'server_group': copy.deepcopy(_server_group_response),
    },
    'required': ['server_group'],
    'additionalProperties': True,
}

show_response_v213 = copy.deepcopy(show_response)
show_response_v213['properties']['server_group'] = _server_group_response_v213

show_response_v215 = copy.deepcopy(show_response)
show_response_v215['properties']['server_group'] = _server_group_response_v215

show_response_v264 = copy.deepcopy(show_response_v213)
show_response_v264['properties']['server_group'] = _server_group_response_v264

delete_response = {'type': 'null'}

index_response = {
    'type': 'object',
    'properties': {
        'server_groups': {
            'type': 'array',
            'items': copy.deepcopy(_server_group_response),
        },
    },
    'required': ['server_groups'],
    'additionalProperties': True,
}

index_response_v213 = copy.deepcopy(index_response)
index_response_v213['properties']['server_groups'][
    'items'
] = _server_group_response_v213

index_response_v215 = copy.deepcopy(index_response_v213)
index_response_v215['properties']['server_groups'][
    'items'
] = _server_group_response_v215

index_response_v264 = copy.deepcopy(index_response_v215)
index_response_v264['properties']['server_groups'][
    'items'
] = _server_group_response_v264


create_response = copy.deepcopy(show_response)

create_response_v213 = copy.deepcopy(show_response_v213)

create_response_v215 = copy.deepcopy(show_response_v215)

create_response_v264 = copy.deepcopy(show_response_v264)
