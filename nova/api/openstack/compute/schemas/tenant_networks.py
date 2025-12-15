# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# NOTE(stephenfin): These schemas are intentionally empty since these APIs have
# been removed

create = {}

index_query = {}
show_query = {}

_tenant_network_response = {
    'type': 'object',
    'properties': {
        'cidr': {
            'oneOf': [
                {'const': 'None'},
                {'type': 'string', 'format': 'cidr'},
            ]
        },
        'id': {'type': 'string', 'format': 'uuid'},
        'label': {'type': 'string'},
    },
    'required': ['cidr', 'id', 'label'],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        'networks': {
            'type': 'array',
            'items': _tenant_network_response,
        }
    },
    'required': ['networks'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'network': _tenant_network_response,
    },
    'required': ['network'],
    'additionalProperties': False,
}

delete_response = {}
create_response = {}
