# Copyright 2015 NEC Corporation.  All rights reserved.
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
                'project_id': parameter_types.project_id,
                'multi_host': parameter_types.boolean,
                'gateway': parameter_types.ipv4,
                'gateway_v6': parameter_types.ipv6,
                'bridge': {
                    'type': 'string',
                },
                'bridge_interface': {
                    'type': 'string',
                },
                # NOTE: In _extract_subnets(), dns1, dns2 dhcp_server are
                # used only for IPv4, not IPv6.
                'dns1': parameter_types.ipv4,
                'dns2': parameter_types.ipv4,
                'dhcp_server': parameter_types.ipv4,

                'fixed_cidr': parameter_types.cidr,
                'allowed_start': parameter_types.ip_address,
                'allowed_end': parameter_types.ip_address,
                'enable_dhcp': parameter_types.boolean,
                'share_address': parameter_types.boolean,
                'mtu': parameter_types.positive_integer_with_empty_str,
                'vlan': parameter_types.positive_integer_with_empty_str,
                'vlan_start': parameter_types.positive_integer_with_empty_str,
                'vpn_start': {
                    'type': 'string',
                },
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

add_network_to_project = {
    'type': 'object',
    'properties': {
        'id': {'type': ['string', 'null']}
    },
    'required': ['id'],
    'additionalProperties': False
}
