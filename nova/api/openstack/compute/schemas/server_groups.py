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
                    'items': [
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
policies['items'][0]['enum'].extend(['soft-anti-affinity', 'soft-affinity'])

create_v264 = copy.deepcopy(create_v215)
del create_v264['properties']['server_group']['properties']['policies']
sg_properties = create_v264['properties']['server_group']
sg_properties['required'].remove('policies')
sg_properties['required'].append('policy')
sg_properties['properties']['policy'] = {
    'type': 'string',
    'enum': ['anti-affinity', 'affinity',
             'soft-anti-affinity', 'soft-affinity'],
}

sg_properties['properties']['rules'] = {
    'type': 'object',
    'properties': {
        'max_server_per_host':
            parameter_types.positive_integer,
    },
    'additionalProperties': False,
}

server_groups_query_param = {
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

update = {
    'type': 'object',
    'properties': {
        'add_members': {
            'type': 'array',
            'items': parameter_types.server_id,
        },
        'remove_members': {
            'type': 'array',
            'items': parameter_types.server_id,
        }
    },
    'additionalProperties': False
}

server_groups_query_param_275 = copy.deepcopy(server_groups_query_param)
server_groups_query_param_275['additionalProperties'] = False
