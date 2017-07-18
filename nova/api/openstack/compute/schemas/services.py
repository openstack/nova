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

service_update = {
    'type': 'object',
    'properties': {
        'host': parameter_types.hostname,
        'binary': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
        },
        'disabled_reason': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
        }
    },
    'required': ['host', 'binary'],
    'additionalProperties': False
}

service_update_v211 = {
    'type': 'object',
    'properties': {
        'host': parameter_types.hostname,
        'binary': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
        },
        'disabled_reason': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
        },
        'forced_down': parameter_types.boolean
    },
    'required': ['host', 'binary'],
    'additionalProperties': False
}

# The 2.53 body is for updating a service's status and/or forced_down fields.
# There are no required attributes since the service is identified using a
# unique service_id on the request path, and status and/or forced_down can
# be specified in the body. If status=='disabled', then 'disabled_reason' is
# also checked in the body but is not required. Requesting status='enabled' and
# including a 'disabled_reason' results in a 400, but this is checked in code.
service_update_v2_53 = {
    'type': 'object',
    'properties': {
        'status': {
            'type': 'string',
            'enum': ['enabled', 'disabled'],
        },
        'disabled_reason': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
        },
        'forced_down': parameter_types.boolean
    },
    'additionalProperties': False
}
