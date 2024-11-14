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
add = {}
disassociate = {}

index_query = {}
show_query = {}

# NOTE(stephenfin): This is a *very* loose schema since this is a deprecated
# API and only the id and label fields are populated with non-null values these
# days.
_network_response = {
    'type': 'object',
    'properties': {
        'bridge': {'type': ['string', 'null']},
        'bridge_interface': {'type': ['string', 'null']},
        'broadcast': {'type': ['string', 'null']},
        'cidr': {'type': ['string', 'null']},
        'cidr_v6': {'type': ['string', 'null']},
        'created_at': {'type': ['string', 'null']},
        'deleted': {'type': ['string', 'null']},
        'deleted_at': {'type': ['string', 'null']},
        'dhcp_server': {'type': ['string', 'null']},
        'dhcp_start': {'type': ['string', 'null']},
        'dns1': {'type': ['string', 'null']},
        'dns2': {'type': ['string', 'null']},
        'enable_dhcp': {'type': ['string', 'null']},
        'gateway': {'type': ['string', 'null']},
        'gateway_v6': {'type': ['string', 'null']},
        'host': {'type': ['string', 'null']},
        'id': {'type': 'string', 'format': 'string'},
        'injected': {'type': ['string', 'null']},
        'label': {'type': 'string'},
        'multi_host': {'type': ['string', 'null']},
        'mtu': {'type': ['integer', 'null']},
        'netmask': {'type': ['string', 'null']},
        'netmask_v6': {'type': ['string', 'null']},
        'priority': {'type': ['string', 'null']},
        'project_id': {'type': ['string', 'null']},
        'rxtx_base': {'type': ['string', 'null']},
        'share_address': {'type': ['string', 'null']},
        'updated_at': {'type': ['string', 'null']},
        'vlan': {'type': ['string', 'null']},
        'vpn_private_address': {'type': ['string', 'null']},
        'vpn_public_address': {'type': ['string', 'null']},
        'vpn_public_port': {'type': ['integer', 'null']},
    },
    'required': [
        # admin fields are optional, but the rest will always be shown
        'broadcast',
        'cidr',
        'cidr_v6',
        'dns1',
        'dns2',
        'gateway',
        'gateway_v6',
        'id',
        'label',
        'netmask',
        'netmask_v6',
    ],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        'networks': {
            'type': 'array',
            'items': _network_response,
        },
    },
    'required': ['networks'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'network': _network_response,
    },
    'required': ['network'],
    'additionalProperties': False,
}

disassociate_response = {}
delete_response = {}
create_response = {}
add_response = {}
