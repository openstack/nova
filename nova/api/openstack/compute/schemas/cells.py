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
        'cell': {
            'type': 'object',
            'properties': {
                'name': parameter_types.cell_name,
                'type': {
                    'type': 'string',
                    'enum': ['parent', 'child'],
                },

                # NOTE: In unparse_transport_url(), a url consists of the
                # following parameters:
                #  "qpid://<username>:<password>@<rpc_host>:<rpc_port>/"
                #  or
                #  "rabiit://<username>:<password>@<rpc_host>:<rpc_port>/"
                # Then the url is stored into transport_url of cells table
                # which is defined with String(255).
                'username': {
                    'type': 'string', 'maxLength': 255,
                    'pattern': '^[a-zA-Z0-9-_]*$'
                },
                'password': {
                    # Allow to specify any string for strong password.
                    'type': 'string', 'maxLength': 255,
                },
                'rpc_host': parameter_types.hostname_or_ip_address,
                'rpc_port': parameter_types.tcp_udp_port,
                'rpc_virtual_host': parameter_types.hostname_or_ip_address,
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['cell'],
    'additionalProperties': False,
}


create_v20 = copy.deepcopy(create)
create_v20['properties']['cell']['properties']['name'] = (parameter_types.
    cell_name_leading_trailing_spaces)


update = {
    'type': 'object',
    'properties': {
        'cell': {
            'type': 'object',
            'properties': {
                'name': parameter_types.cell_name,
                'type': {
                    'type': 'string',
                    'enum': ['parent', 'child'],
                },
                'username': {
                    'type': 'string', 'maxLength': 255,
                    'pattern': '^[a-zA-Z0-9-_]*$'
                },
                'password': {
                    'type': 'string', 'maxLength': 255,
                },
                'rpc_host': parameter_types.hostname_or_ip_address,
                'rpc_port': parameter_types.tcp_udp_port,
                'rpc_virtual_host': parameter_types.hostname_or_ip_address,
            },
            'additionalProperties': False,
        },
    },
    'required': ['cell'],
    'additionalProperties': False,
}


update_v20 = copy.deepcopy(create)
update_v20['properties']['cell']['properties']['name'] = (parameter_types.
    cell_name_leading_trailing_spaces)


sync_instances = {
    'type': 'object',
    'properties': {
        'project_id': parameter_types.project_id,
        'deleted': parameter_types.boolean,
        'updated_since': {
            'type': 'string',
            'format': 'date-time',
        },
    },
    'additionalProperties': False,
}
