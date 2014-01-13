# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

add_tenant_access = {
    'type': 'object',
    'properties': {
        'add_tenant_access': {
            'type': 'object',
            'properties': {
                'tenant_id': {
                    # defined from project_id in instance_type_projects table
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'required': ['tenant_id'],
            'additionalProperties': False,
        },
    },
    'required': ['add_tenant_access'],
    'additionalProperties': False,
}


remove_tenant_access = {
    'type': 'object',
    'properties': {
        'remove_tenant_access': {
            'type': 'object',
            'properties': {
                'tenant_id': {
                    # defined from project_id in instance_type_projects table
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'required': ['tenant_id'],
            'additionalProperties': False,
        },
    },
    'required': ['remove_tenant_access'],
    'additionalProperties': False,
}
