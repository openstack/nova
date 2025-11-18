# Copyright 2014 IBM Corporation.  All rights reserved.
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
        'snapshot': {
            'type': 'object',
            'properties': {
                'volume_id': {'type': 'string'},
                'force': parameter_types.boolean,
                'display_name': {'type': 'string'},
                'display_description': {'type': 'string'},
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['snapshot'],
    'additionalProperties': False,
}

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'offset': parameter_types.multi_params(
             parameter_types.non_negative_integer)
    },
    'additionalProperties': True
}

detail_query = index_query

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True
}

_snapshot_response = {
    'type': 'object',
    'properties': {
        'createdAt': {'type': 'string', 'format': 'date-time'},
        'displayDescription': {'type': ['string', 'null']},
        'displayName': {'type': ['string', 'null']},
        'id': {'type': 'string', 'format': 'uuid'},
        'volumeId': {'type': 'string', 'format': 'uuid'},
        'size': {'type': 'integer'},
        'status': {
            'type': 'string',
            # https://github.com/openstack/cinder/blob/26.0.0/cinder/objects/fields.py#L120-L129
            'enum': [
                'error',
                'available',
                'creating',
                'deleting',
                'deleted',
                # 'updating' is omitted since it is unused in Cinder
                'error_deleting',
                'unmanaging',
                'backing-up',
                'restoring',
            ],
        },
    },
    'required': [
        'createdAt',
        'displayDescription',
        'displayName',
        'id',
        'volumeId',
        'size',
        'status',
    ],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'snapshot': _snapshot_response,
    },
    'required': ['snapshot'],
    'additionalProperties': False,
}

delete_response = {'type': 'null'}

index_response = {
    'type': 'object',
    'properties': {
        'snapshots': {
            'type': 'array',
            'items': _snapshot_response,
        },
    },
    'required': ['snapshots'],
    'additionalProperties': False,
}

detail_response = {
    'type': 'object',
    'properties': {
        'snapshots': {
            'type': 'array',
            'items': _snapshot_response,
        },
    },
    'required': ['snapshots'],
    'additionalProperties': False,
}

create_response = {
    'type': 'object',
    'properties': {
        'snapshot': _snapshot_response,
    },
    'required': ['snapshot'],
    'additionalProperties': False,
}
