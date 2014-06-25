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

from nova.api.openstack.compute.plugins.v3 import flavor_rxtx
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
                # positive ( > 0) integer
                'ram': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]*$', 'minimum': 1
                },
                # positive ( > 0) integer
                'vcpus': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]*$', 'minimum': 1
                },
                # non-negative ( >= 0) integer
                'disk': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]*$', 'minimum': 0
                },
                # non-negative ( >= 0) integer
                'ephemeral': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]*$', 'minimum': 0
                },
                # non-negative ( >= 0) integer
                'swap': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]*$', 'minimum': 0
                },
                # positive ( > 0) float
                '%s:rxtx_factor' % flavor_rxtx.ALIAS: {
                    'type': ['number', 'string'],
                    'pattern': '^[0-9]+(\.[0-9]+)?$',
                    'minimum': 0, 'exclusiveMinimum': True
                },
                'flavor-access:is_public': parameter_types.boolean,
            },
            'required': ['name', 'id', 'ram', 'vcpus', 'disk'],
            'additionalProperties': False,
        },
    },
    'required': ['flavor'],
    'additionalProperties': False,
}
