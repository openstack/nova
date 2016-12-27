# Copyright 2015 NEC Corporation. All rights reserved.
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

create = {
    'type': 'object',
    'properties': {
        'network': {
            'type': 'object',
            'properties': {
                'label': {
                    'type': 'string', 'maxLength': 255
                },
                'ipam': parameter_types.boolean,
                'cidr': parameter_types.cidr,
                'cidr_v6': parameter_types.cidr,
                'vlan_start': parameter_types.positive_integer_with_empty_str,
                'network_size':
                    parameter_types.positive_integer_with_empty_str,
                'num_networks': parameter_types.positive_integer_with_empty_str
            },
            'required': ['label'],
            'oneOf': [
                {'required': ['cidr']},
                {'required': ['cidr_v6']}
            ],
            'additionalProperties': False,
        },
    },
    'required': ['network'],
    'additionalProperties': False,
}
