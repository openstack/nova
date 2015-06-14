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


ip_range = {
    # TODO(eliqiao) need to find a better pattern
    'type': 'string',
    'pattern': '^[0-9./a-fA-F]*$',
}

create = {
    'type': 'object',
    'properties': {
        'floating_ips_bulk_create': {
            'type': 'object',
            'properties': {
                'ip_range': ip_range,
                'pool': {
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
                'interface': {
                    'type': 'string', 'minLength': 1, 'maxLength': 255,
                },
            },
            'required': ['ip_range'],
            'additionalProperties': False,
        },
    },
    'required': ['floating_ips_bulk_create'],
    'additionalProperties': False,
}


delete = {
    'type': 'object',
    'properties': {
        'ip_range': ip_range,
    },
    'required': ['ip_range'],
    'additionalProperties': False,
}
