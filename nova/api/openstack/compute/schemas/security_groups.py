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

create = {
    'type': 'object',
    'properties': {
        'security_group': {
            'type': 'object',
            'properties': {
                'name': {
                    'type': 'string',
                    'minLength': 0,
                    'maxLength': 255,
                },
                'description': {
                    'type': 'string',
                    'minLength': 0,
                    'maxLength': 255,
                },
            },
            'required': ['name', 'description'],
            # NOTE(stephenfin): Per gmann's note below
            'additionalProperties': True,
        },
    },
    'required': ['security_group'],
    # NOTE(stephenfin): Per gmann's note below
    'additionalProperties': True,
}

update = create

create_rules = {
    'type': 'object',
    'properties': {
        'security_group_rule': {
            'type': 'object',
            'properties': {
                'group_id': {
                    'oneOf': [
                        {'type': 'null'},
                        {'type': 'string', 'format': 'uuid'},
                    ],
                },
                'parent_group_id': {
                    'type': 'string',
                    'format': 'uuid',
                },
                # NOTE(stephenfin): We never validated these and we're not
                # going to add that validation now.
                'to_port': {},
                'from_port': {},
                'ip_protocol': {},
                'cidr': {},
            },
            'required': ['parent_group_id'],
            # NOTE(stephenfin): Per gmann's note below
            'additionalProperties': True,
        },
    },
    'required': ['security_group_rule'],
    # NOTE(stephenfin): Per gmann's note below
    'additionalProperties': True,

}

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'offset': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'all_tenants': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. This API is deprecated in microversion 2.36 so we
    # do not to update the additionalProperties to False.
    'additionalProperties': True
}

# TODO(stephenfin): Remove additionalProperties in a future API version
server_sg_index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
add_security_group = {
    'type': 'object',
    'properties': {
        'name': {
            'type': 'string',
            'minLength': 1,
        },
    },
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
remove_security_group = {
    'type': 'object',
    'properties': {
        'name': {
            'type': 'string',
            'minLength': 1,
        },
    },
    'additionalProperties': True,
}
