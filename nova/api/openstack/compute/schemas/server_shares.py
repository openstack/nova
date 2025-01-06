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
    'title': 'Server shares',
    'type': 'object',
    'properties': {
        'share': {
            'type': 'object',
            'properties': {
                'share_id': parameter_types.share_id,
                'tag': parameter_types.share_tag,
            },
            'required': ['share_id'],
            'additionalProperties': False
        }
    },
    'required': ['share'],
    'additionalProperties': False
}

index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': False
}

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': False
}

# "share": {
#   "uuid": "68ba1762-fd6d-4221-8311-f3193dd93404",
#   "export_location": "10.0.0.50:/mnt/foo",
#   "share_id": "e8debdc0-447a-4376-a10a-4cd9122d7986",
#   "status": "inactive",
#   "tag": "e8debdc0-447a-4376-a10a-4cd9122d7986"
# }

_share_response = {
    'type': 'object',
    'properties': {
        'export_location': parameter_types.share_export_location,
        'share_id': parameter_types.share_id,
        'status': parameter_types.share_status,
        'tag': parameter_types.share_tag,
        'uuid': parameter_types.share_id,
    },
    'required': ['share_id', 'status', 'tag'],
    'additionalProperties': False
}

show_response = {
    'title': 'Server share',
    'type': 'object',
    'properties': {
        'share': _share_response
    },
    'required': ['share'],
    'additionalProperties': False
}

index_response = {
    'title': 'Server shares',
    'type': 'object',
    'properties': {
        'shares': {
            'type': 'array',
            'items': _share_response
        },
    },
    'required': ['shares'],
    'additionalProperties': False
}
