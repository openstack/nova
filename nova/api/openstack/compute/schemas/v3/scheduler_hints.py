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

from nova.api.validation import parameter_types


_hints = {
    'type': 'object',
    'properties': {
        'group': {
            # NOTE: The value of 'group' is stored to value which is
            # defined as varchar(255) in instance_system_metadata table.
            'type': 'string', 'maxLength': 255,
        },
        'different_host': {
            # NOTE: The value of 'different_host' is the set of server
            # uuids where a new server is scheduled on a different host.
            # A user can specify one server as string parameter and should
            # specify multiple servers as array parameter instead.
            'type': ['string', 'array'],
            'format': 'uuid',
            'items': parameter_types.server_id
        },
        'same_host': {
            # NOTE: The value of 'different_host' is the set of server
            # uuids where a new server is scheduled on the same host.
            'type': ['string', 'array'],
            'items': parameter_types.server_id
        },
        'query': {
            # NOTE: The value of 'query' is converted to dict data with
            # jsonutils.loads() and used for filtering hosts.
            'type': ['string', 'object'],
        },
        # NOTE: The value of 'target_cell' is the cell name what cell
        # a new server is scheduled on.
        'target_cell': parameter_types.name,
        'build_near_host_ip': parameter_types.ip_address,
        'cidr': {
            'type': 'string',
            'pattern': '^\/[0-9a-f.:]+$'
        },
    },
    'additionalProperties': False
}


server_create = {
    'os:scheduler_hints': _hints,
    'OS-SCH-HNT:scheduler_hints': _hints,
}
