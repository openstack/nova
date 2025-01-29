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


add_tenant_access = {
    'type': 'object',
    'properties': {
        'addTenantAccess': {
            'type': 'object',
            'properties': {
                'tenant': {
                    # defined from project_id in instance_type_projects table
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'required': ['tenant'],
            'additionalProperties': False,
        },
    },
    'required': ['addTenantAccess'],
    'additionalProperties': False,
}

remove_tenant_access = {
    'type': 'object',
    'properties': {
        'removeTenantAccess': {
            'type': 'object',
            'properties': {
                'tenant': {
                    # defined from project_id in instance_type_projects table
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'required': ['tenant'],
            'additionalProperties': False,
        },
    },
    'required': ['removeTenantAccess'],
    'additionalProperties': False,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_common_response = {
    'type': 'object',
    'properties': {
        'flavor_access': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'flavor_id': {'type': 'string'},
                    'tenant_id': parameter_types.project_id,
                },
                'required': ['flavor_id', 'tenant_id'],
                'additionalProperties': True,
            },
        },
    },
    'required': ['flavor_access'],
    'additionalProperties': True,
}

index_response = copy.deepcopy(_common_response)

add_tenant_access_response = copy.deepcopy(_common_response)

remove_tenant_access_response = copy.deepcopy(_common_response)
