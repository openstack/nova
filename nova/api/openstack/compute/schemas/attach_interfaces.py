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


create = {
    'type': 'object',
    'properties': {
        'interfaceAttachment': {
            'type': 'object',
            'properties': {
                # NOTE: This parameter is passed to the search_opts of
                # Neutron list_network API: search_opts = {'id': net_id}
                'net_id': parameter_types.network_id,
                # NOTE: This parameter is passed to Neutron show_port API
                # as a port id.
                'port_id': parameter_types.network_port_id,
                'fixed_ips': {
                    'type': 'array', 'minItems': 1, 'maxItems': 1,
                    'items': {
                        'type': 'object',
                        'properties': {
                            'ip_address': parameter_types.ip_address
                        },
                        'required': ['ip_address'],
                        'additionalProperties': False,
                    },
                },
            },
            'additionalProperties': False,
        },
    },
    'additionalProperties': False,
}

create_v249 = copy.deepcopy(create)
create_v249['properties']['interfaceAttachment']['properties']['tag'] = parameter_types.tag  # noqa: E501

# TODO(stephenfin): Remove additionalProperties in a future API version
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_interface_attachment = {
    'type': 'object',
    'properties': {
        'fixed_ips': {
            'type': ['null', 'array'],
            'items': {
                'type': 'object',
                'properties': {
                    'ip_address': {
                        'type': 'string',
                        'anyOf': [
                            {'format': 'ipv4'},
                            {'format': 'ipv6'},
                        ],
                    },
                    'subnet_id': {'type': 'string', 'format': 'uuid'},
                },
                'required': ['ip_address', 'subnet_id'],
                'additionalProperties': False,
            },
        },
        'mac_addr': {'type': 'string', 'format': 'mac-address'},
        'net_id': {'type': 'string', 'format': 'uuid'},
        'port_id': {'type': 'string', 'format': 'uuid'},
        'port_state': {'type': 'string'},
    },
    'required': ['fixed_ips', 'mac_addr', 'net_id', 'port_id', 'port_state'],
    'additionalProperties': False,
}

_interface_attachment_v270 = copy.deepcopy(_interface_attachment)
_interface_attachment_v270['properties']['tag'] = {
    'type': ['null', 'string'],
}
_interface_attachment_v270['required'].append('tag')

index_response = {
    'type': 'object',
    'properties': {
        'interfaceAttachments': {
            'type': 'array',
            'items': copy.deepcopy(_interface_attachment),
        },
    },
    'required': ['interfaceAttachments'],
    'additionalProperties': False,
}

index_response_v270 = copy.deepcopy(index_response)
index_response_v270['properties']['interfaceAttachments']['items'] = copy.deepcopy(  # noqa: E501
    _interface_attachment_v270
)

show_response = {
    'type': 'object',
    'properties': {
        'interfaceAttachment': copy.deepcopy(_interface_attachment),
    },
    'required': ['interfaceAttachment'],
    'additionalProperties': False,
}

show_response_v270 = copy.deepcopy(show_response)
show_response_v270['properties']['interfaceAttachment'] = copy.deepcopy(
    _interface_attachment_v270
)

# create responses are identical to show, including microversions
create_response = copy.deepcopy(show_response)
create_response_v270 = copy.deepcopy(show_response_v270)

delete_response = {
    'type': 'null',
}
