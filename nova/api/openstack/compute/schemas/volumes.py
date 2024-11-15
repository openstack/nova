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
from nova.api.validation import response_types

create = {
    'type': 'object',
    'properties': {
        'volume': {
            'type': 'object',
            'properties': {
                'volume_type': {'type': 'string'},
                'metadata': {'type': 'object'},
                'snapshot_id': {'type': 'string'},
                'size': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]+$',
                    'minimum': 1
                },
                'availability_zone': {'type': 'string'},
                'display_name': {'type': 'string'},
                'display_description': {'type': 'string'},
            },
            'required': ['size'],
            'additionalProperties': False,
        },
    },
    'required': ['volume'],
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

_volume_response = {
    'type': 'object',
    'properties': {
        'attachments': {
            'type': 'array',
            # either a list of attachments or a list with a single empty object
            'oneOf': [
                {
                    'items': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'string', 'format': 'uuid'},
                            'device': {'type': 'string'},
                            'serverId': {'type': 'string', 'format': 'uuid'},
                            'volumeId': {'type': 'string', 'format': 'uuid'},
                        },
                        'required': ['id', 'serverId', 'volumeId'],
                        'additionalProperties': False,
                    },
                },
                {
                    'prefixItems': [
                        {
                            'type': 'object',
                            'properties': {},
                            'required': [],
                            'additionalProperties': False,
                        }
                    ],
                },
            ],
            'additionalItems': False,
        },
        'availabilityZone': {'type': ['string', 'null']},
        'createdAt': {'type': 'string', 'format': 'date-time'},
        'displayDescription': {'type': ['string', 'null']},
        'displayName': {'type': ['string', 'null']},
        'id': {'type': 'string', 'format': 'uuid'},
        'metadata': response_types.metadata,
        'size': {'type': 'integer'},
        'snapshotId': {
            'oneOf': [
                {'type': 'string', 'format': 'uuid'},
                {'type': 'null'},
            ],
        },
        'status': {
            'type': 'string',
            # https://github.com/openstack/cinder/blob/26.0.0/cinder/objects/fields.py#L168-L190
            'enum': [
                'creating',
                'available',
                'deleting',
                'error',
                'error_deleting',
                # 'error_managing' is mapped to 'error'
                # 'managing' is mapped to 'creating'
                'attaching',
                'in-use',
                'detaching',
                'maintenance',
                'restoring-backup',
                'error_restoring',
                'reserved',
                'awaiting-transfer',
                'backing-up',
                'error_backing-up',
                'error_extending',
                'downloading',
                'uploading',
                'retyping',
                'extending',
            ],
        },
        'volumeType': {'type': ['string', 'null']},
    },
    'required': [
        'attachments',
        'availabilityZone',
        'createdAt',
        'displayDescription',
        'displayName',
        'id',
        'metadata',
        'size',
        'snapshotId',
        'status',
        'volumeType',
    ],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'volume': _volume_response,
    },
    'required': ['volume'],
    'additionalProperties': False,
}

delete_response = {'type': 'null'}

# NOTE(stephenfin): Yes, the index and detail responses are exactly the same
index_response = {
    'type': 'object',
    'properties': {
        'volumes': {
            'type': 'array',
            'items': _volume_response,
        },
    },
    'required': ['volumes'],
    'additionalProperties': False,
}

detail_response = {
    'type': 'object',
    'properties': {
        'volumes': {
            'type': 'array',
            'items': _volume_response,
        },
    },
    'required': ['volumes'],
    'additionalProperties': False,
}

create_response = {
    'type': 'object',
    'properties': {
        'volume': _volume_response,
    },
    'required': ['volume'],
    'additionalProperties': False,
}
