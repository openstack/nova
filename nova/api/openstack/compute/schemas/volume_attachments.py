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

import copy

from nova.api.validation import parameter_types

create = {
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
                },
            },
            'required': ['volumeId'],
            'additionalProperties': False,
        },
    },
    'required': ['volumeAttachment'],
    'additionalProperties': False,
}
create_v249 = copy.deepcopy(create)
create_v249['properties']['volumeAttachment'][
    'properties']['tag'] = parameter_types.tag

create_v279 = copy.deepcopy(create_v249)
create_v279['properties']['volumeAttachment'][
    'properties']['delete_on_termination'] = parameter_types.boolean

update = copy.deepcopy(create)
del update['properties']['volumeAttachment']['properties']['device']

# NOTE(brinzhang): Allow attachment_id, serverId, device, tag, and
# delete_on_termination (i.e., follow the content of the GET response)
# to be specified for RESTfulness, even though we will not allow updating
# all of them.
update_v285 = {
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
                },
                'tag': parameter_types.tag,
                'delete_on_termination': parameter_types.boolean,
                'serverId': parameter_types.server_id,
                'id': parameter_types.attachment_id
            },
            'required': ['volumeId'],
            'additionalProperties': False,
        },
    },
    'required': ['volumeAttachment'],
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
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_v275 = copy.deepcopy(index_query)
index_query_v275['additionalProperties'] = False

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}
