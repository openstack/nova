# Copyright 2017 NEC Corporation.  All rights reserved.
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

# NOTE(takashin): The following sort keys are defined for backward
# compatibility. If they are changed, the API microversion should be bumped.
VALID_SORT_KEYS = [
    'created_at', 'description', 'disabled', 'ephemeral_gb', 'flavorid', 'id',
    'is_public', 'memory_mb', 'name', 'root_gb', 'rxtx_factor', 'swap',
    'updated_at', 'vcpu_weight', 'vcpus'
]

VALID_SORT_DIR = ['asc', 'desc']

create = {
    'type': 'object',
    'properties': {
        'flavor': {
            'type': 'object',
            'properties': {
                # in nova/flavors.py, name with all white spaces is forbidden.
                'name': parameter_types.name,
                # forbid leading/trailing whitespaces
                'id': {
                    'type': ['string', 'number', 'null'],
                    'minLength': 1, 'maxLength': 255,
                    'pattern': '^(?! )[a-zA-Z0-9. _-]+(?<! )$'
                },
                'ram': parameter_types.flavor_param_positive,
                'vcpus': parameter_types.flavor_param_positive,
                'disk': parameter_types.flavor_param_non_negative,
                'OS-FLV-EXT-DATA:ephemeral':
                    parameter_types.flavor_param_non_negative,
                'swap': parameter_types.flavor_param_non_negative,
                # positive ( > 0) float
                'rxtx_factor': {
                    'type': ['number', 'string'],
                    'pattern': r'^[0-9]+(\.[0-9]+)?$',
                    # this is a float, so we want to allow everything close to
                    # 0 (e.g. 0.1) but not 0 itself, hence exclusiveMinimum
                    # rather than the usual minimum
                    'exclusiveMinimum': 0,
                    # maximum's value is limited to db constant's
                    # SQL_SP_FLOAT_MAX (in nova/db/constants.py)
                    'maximum': 3.40282e+38
                },
                'os-flavor-access:is_public': parameter_types.boolean,
            },
            # TODO(oomichi): 'id' should be required with v2.1+microversions.
            # On v2.0 API, nova-api generates a flavor-id automatically if
            # specifying null as 'id' or not specifying 'id'. Ideally a client
            # should specify null as 'id' for requesting auto-generated id
            # exactly. However, this strict limitation causes a backwards
            # incompatible issue on v2.1. So now here relaxes the requirement
            # of 'id'.
            'required': ['name', 'ram', 'vcpus', 'disk'],
            'additionalProperties': False,
        },
    },
    'required': ['flavor'],
    'additionalProperties': False,
}


create_v20 = copy.deepcopy(create)
create_v20['properties']['flavor']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces
)


# 2.55 adds an optional description field with a max length of 65535 since the
# backing database column is a TEXT column which is 64KiB.
_flavor_description = {
    'type': ['string', 'null'], 'minLength': 0, 'maxLength': 65535,
    'pattern': parameter_types.valid_description_regex,
}


create_v2_55 = copy.deepcopy(create)
create_v2_55['properties']['flavor']['properties']['description'] = (
    _flavor_description)


update_v2_55 = {
    'type': 'object',
    'properties': {
        'flavor': {
            'type': 'object',
            'properties': {
                'description': _flavor_description
            },
            # Since the only property that can be specified on update is the
            # description field, it is required. If we allow updating other
            # flavor attributes in a later microversion, we should reconsider
            # what is required.
            'required': ['description'],
            'additionalProperties': False,
        },
    },
    'required': ['flavor'],
    'additionalProperties': False,
}

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'marker': parameter_types.multi_params({'type': 'string'}),
        'is_public': parameter_types.multi_params({'type': 'string'}),
        'minRam': parameter_types.multi_params({'type': 'string'}),
        'minDisk': parameter_types.multi_params({'type': 'string'}),
        'sort_key': parameter_types.multi_params({'type': 'string',
                                                  'enum': VALID_SORT_KEYS}),
        'sort_dir': parameter_types.multi_params({'type': 'string',
                                                  'enum': VALID_SORT_DIR})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_275 = copy.deepcopy(index_query)
index_query_275['additionalProperties'] = False

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}
