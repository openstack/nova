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


from nova.api.validation import parameter_types


domain_entry_update = {
    'type': 'object',
    'properties': {
        'domain_entry': {
            'type': 'object',
            'properties': {
                'scope': {
                    'type': 'string',
                    'enum': ['public', 'private'],
                },
                'project': parameter_types.project_id,
                'availability_zone': parameter_types.name,
            },
            'required': ['scope'],
            'maxProperties': 2,
            'additionalProperties': False,
        },
    },
    'required': ['domain_entry'],
    'additionalProperties': False,
}


dns_entry_update = {
    'type': 'object',
    'properties': {
        'dns_entry': {
            'type': 'object',
            'properties': {
                'ip': parameter_types.ip_address,
                'dns_type': {
                    'type': 'string',
                    'enum': ['a', 'A'],
                },
            },
            'required': ['ip', 'dns_type'],
            'additionalProperties': False,
        },
    },
    'required': ['dns_entry'],
    'additionalProperties': False,
}
