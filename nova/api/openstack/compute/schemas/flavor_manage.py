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

import copy

from nova.api.validation import parameter_types

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
                    'minimum': 0, 'exclusiveMinimum': True,
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
create_v20['properties']['flavor']['properties']['name'] = (parameter_types.
    name_with_leading_trailing_spaces)


# 2.55 adds an optional description field with a max length of 65535 since the
# backing database column is a TEXT column which is 64KiB.
flavor_description = {
    'type': ['string', 'null'], 'minLength': 0, 'maxLength': 65535,
    'pattern': parameter_types.valid_description_regex,
}


create_v2_55 = copy.deepcopy(create)
create_v2_55['properties']['flavor']['properties']['description'] = (
    flavor_description)


update_v2_55 = {
    'type': 'object',
    'properties': {
        'flavor': {
            'type': 'object',
            'properties': {
                'description': flavor_description
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
