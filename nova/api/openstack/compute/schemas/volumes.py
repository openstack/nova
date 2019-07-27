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

import copy

from nova.api.validation import parameter_types

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


snapshot_create = {
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

create_volume_attachment = {
    'type': 'object',
    'properties': {
        'volumeAttachment': {
            'type': 'object',
            'properties': {
                'volumeId': parameter_types.volume_id,
                'device': {
                    'type': ['string', 'null'],
                    # NOTE: The validation pattern from match_device() in
                    #       nova/block_device.py.
                    'pattern': '(^/dev/x{0,1}[a-z]{0,1}d{0,1})([a-z]+)[0-9]*$'
                }
            },
            'required': ['volumeId'],
            'additionalProperties': False,
        },
    },
    'required': ['volumeAttachment'],
    'additionalProperties': False,
}
create_volume_attachment_v249 = copy.deepcopy(create_volume_attachment)
create_volume_attachment_v249['properties']['volumeAttachment'][
                              'properties']['tag'] = parameter_types.tag

create_volume_attachment_v279 = copy.deepcopy(create_volume_attachment_v249)
create_volume_attachment_v279['properties']['volumeAttachment'][
    'properties']['delete_on_termination'] = parameter_types.boolean

update_volume_attachment = copy.deepcopy(create_volume_attachment)
del update_volume_attachment['properties']['volumeAttachment'][
    'properties']['device']

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'offset': parameter_types.multi_params(
             parameter_types.non_negative_integer)
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

detail_query = index_query

index_query_275 = copy.deepcopy(index_query)
index_query_275['additionalProperties'] = False
