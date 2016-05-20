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

# NOTE(russellb) There is one other policy, 'legacy', but we don't allow that
# being set via the API.  It's only used when a group gets automatically
# created to support the legacy behavior of the 'group' scheduler hint.
create = {
    'type': 'object',
    'properties': {
        'server_group': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'policies': {
                    'type': 'array',
                    'items': [{'enum': ['anti-affinity', 'affinity']}],
                    'uniqueItems': True,
                    'additionalItems': False,
                }
            },
            'required': ['name', 'policies'],
            'additionalProperties': False,
        }
    },
    'required': ['server_group'],
    'additionalProperties': False,
}

create_v215 = copy.deepcopy(create)
policies = create_v215['properties']['server_group']['properties']['policies']
policies['items'][0]['enum'].extend(['soft-anti-affinity', 'soft-affinity'])
