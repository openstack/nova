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


create_v255 = copy.deepcopy(create)
create_v255['properties']['flavor']['properties']['description'] = (
    _flavor_description)


update = {
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

_flavor_basic = {
    'type': 'object',
    'properties': {
        'id': {'type': 'string'},
        'links': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'href': {'type': 'string', 'format': 'uri'},
                    'rel': {'type': 'string'},
                },
                'required': ['href', 'rel'],
                'additionalProperties': False,
            },
        },
        'name': {'type': 'string'},
    },
    'required': ['id', 'links', 'name'],
    'additionalProperties': False,
}

_flavor_basic_v255 = copy.deepcopy(_flavor_basic)
_flavor_basic_v255['properties']['description'] = {'type': ['string', 'null']}
_flavor_basic_v255['required'].append('description')

_flavor = {
    'type': 'object',
    'properties': {
        'disk': {'type': 'integer'},
        'id': {'type': 'string'},
        'links': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'href': {'type': 'string', 'format': 'uri'},
                    'rel': {'type': 'string'},
                },
                'required': ['href', 'rel'],
            },
        },
        'name': {'type': 'string'},
        'os-flavor-access:is_public': {},
        'ram': {'type': 'integer'},
        'rxtx_factor': {},
        'swap': {
            'anyOf': [
                {'type': 'integer'},
                {'const': ''},
            ],
        },
        'vcpus': {'type': 'integer'},
        'OS-FLV-EXT-DATA:ephemeral': {'type': 'integer'},
        'OS-FLV-DISABLED:disabled': {'type': 'boolean'},
    },
    'required': [
        'disk',
        'id',
        'links',
        'name',
        'os-flavor-access:is_public',
        'ram',
        'rxtx_factor',
        'swap',
        'vcpus',
        'OS-FLV-DISABLED:disabled',
        'OS-FLV-EXT-DATA:ephemeral',
    ],
    'additionalProperties': False,
}

_flavor_v255 = copy.deepcopy(_flavor)
_flavor_v255['properties']['description'] = {'type': ['string', 'null']}
_flavor_v255['required'].append('description')

_flavor_v261 = copy.deepcopy(_flavor_v255)
_flavor_v261['properties']['extra_specs'] = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:. ]{1,255}$': {'type': 'string', 'maxLength': 255},
    },
    'additionalProperties': False,
}

_flavor_v275 = copy.deepcopy(_flavor_v261)
# we completely overwrite this since the new variant is much simpler
_flavor_v275['properties']['swap'] = {'type': 'integer'}

_flavors_links = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'href': {'type': 'string', 'format': 'uri'},
            'rel': {'type': 'string'},
        },
        'required': ['href', 'rel'],
        'additionalProperties': False,
    },
}

delete_response = {
    'type': 'null',
}

create_response = {
    'type': 'object',
    'properties': {
        'flavor': copy.deepcopy(_flavor),
    },
    'required': ['flavor'],
    'additionalProperties': False,
}

create_response_v255 = copy.deepcopy(create_response)
create_response_v255['properties']['flavor'] = copy.deepcopy(_flavor_v255)

create_response_v261 = copy.deepcopy(create_response_v255)
create_response_v261['properties']['flavor'] = copy.deepcopy(_flavor_v261)

create_response_v275 = copy.deepcopy(create_response_v261)
create_response_v275['properties']['flavor'] = copy.deepcopy(_flavor_v275)

# NOTE(stephenfin): update is only available from 2.55 and the response is
# identical to the create and show response from that point forward
update_response = {
    'type': 'object',
    'properties': {
        'flavor': copy.deepcopy(_flavor_v255),
    },
    'required': ['flavor'],
    'additionalProperties': False,
}

update_response_v261 = copy.deepcopy(update_response)
update_response_v261['properties']['flavor'] = copy.deepcopy(_flavor_v261)

update_response_v275 = copy.deepcopy(update_response_v261)
update_response_v275['properties']['flavor'] = copy.deepcopy(_flavor_v275)

index_response = {
    'type': 'object',
    'properties': {
        'flavors': {
            'type': 'array',
            'items': _flavor_basic,
        },
        'flavors_links': _flavors_links,
    },
    'required': ['flavors'],
    'additionalProperties': False,
}

index_response_v255 = copy.deepcopy(index_response)
index_response_v255['properties']['flavors']['items'] = _flavor_basic_v255

detail_response = {
    'type': 'object',
    'properties': {
        'flavors': {
            'type': 'array',
            'items': _flavor,
        },
        'flavors_links': _flavors_links,
    },
    'required': ['flavors'],
    'additionalProperties': False,
}

detail_response_v255 = copy.deepcopy(detail_response)
detail_response_v255['properties']['flavors']['items'] = _flavor_v255

detail_response_v261 = copy.deepcopy(detail_response_v255)
detail_response_v261['properties']['flavors']['items'] = _flavor_v261

detail_response_v275 = copy.deepcopy(detail_response_v261)
detail_response_v275['properties']['flavors']['items'] = _flavor_v275

show_response = {
    'type': 'object',
    'properties': {
        'flavor': copy.deepcopy(_flavor),
    },
    'required': ['flavor'],
    'additionalProperties': False,
}

show_response_v255 = copy.deepcopy(show_response)
show_response_v255['properties']['flavor'] = copy.deepcopy(_flavor_v255)

show_response_v261 = copy.deepcopy(show_response_v255)
show_response_v261['properties']['flavor'] = copy.deepcopy(_flavor_v261)

show_response_v275 = copy.deepcopy(show_response_v261)
show_response_v275['properties']['flavor'] = copy.deepcopy(_flavor_v275)
