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

server_create = {
    'security_groups': {
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                # NOTE(oomichi): allocate_for_instance() of neutronv2/api.py
                # gets security_group names or UUIDs from this parameter.
                # parameter_types.name allows both format.
                'name': parameter_types.name,
            },
            'additionalProperties': False,
        }
    },
}


server_create_v20 = copy.deepcopy(server_create)
server_create_v20['security_groups']['items']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces)
