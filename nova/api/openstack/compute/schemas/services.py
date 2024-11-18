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

update = {
    'type': 'object',
    'properties': {
        'host': parameter_types.fqdn,
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

update_v211 = {
    'type': 'object',
    'properties': {
        'host': parameter_types.fqdn,
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
update_v253 = {
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


index_query = {
    'type': 'object',
    'properties': {
        'host': parameter_types.common_query_param,
        'binary': parameter_types.common_query_param,
    },
    # For backward compatible changes
    'additionalProperties': True
}

index_query_v275 = copy.deepcopy(index_query)
index_query_v275['additionalProperties'] = False

_service_response = {
    'type': 'object',
    'properties': {
        'binary': {'type': 'string'},
        'disabled_reason': {'type': ['string', 'null']},
        'host': {'type': 'string'},
        'id': {'type': 'integer'},
        'state': {'type': 'string', 'enum': ['up', 'down']},
        'status': {'type': 'string', 'enum': ['enabled', 'disabled']},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'zone': {'type': 'string'},
    },
    'required': [
        'binary',
        'disabled_reason',
        'host',
        'id',
        'state',
        'status',
        'updated_at',
        'zone',
    ],
    'additionalProperties': False,
}

_service_response_v211 = copy.deepcopy(_service_response)
_service_response_v211['properties']['forced_down'] = {'type': 'boolean'}
_service_response_v211['required'].append('forced_down')

_service_response_v253 = copy.deepcopy(_service_response_v211)
_service_response_v253['properties']['id'] = {
    'type': 'string', 'format': 'uuid',
}

_service_response_v269 = copy.deepcopy(_service_response_v253)
_service_response_v269['properties']['status'] = {
    'type': 'string', 'enum': ['enabled', 'disabled', 'UNKNOWN']
}
_service_response_v269['required'] = [
    'binary', 'host', 'status'
]

delete_response = {'type': 'null'}

index_response = {
    'type': 'object',
    'properties': {
        'services': {
            'type': 'array',
            'items': _service_response,
        },
    },
    'required': ['services'],
    'additionalProperties': False,
}

index_response_v211 = copy.deepcopy(index_response)
index_response_v211['properties']['services']['items'] = _service_response_v211

index_response_v253 = copy.deepcopy(index_response_v211)
index_response_v253['properties']['services']['items'] = _service_response_v253

index_response_v269 = copy.deepcopy(index_response_v253)
index_response_v269['properties']['services']['items'] = _service_response_v269

update_response = {
    'type': 'object',
    'properties': {
        'service': {
            'type': 'object',
            'oneOf': [
                {
                    'properties': {
                        'binary': {'type': 'string'},
                        'disabled_reason': {'type': ['string', 'null']},
                        'host': {'type': 'string'},
                        'status': {
                            'type': 'string', 'enum': ['enabled', 'disabled']
                        },
                    },
                    'required': ['binary', 'host', 'status'],
                    # pardon the duplication but this must go *inside* the
                    # sub-schemas
                    # https://github.com/python-jsonschema/jsonschema/issues/193
                    'additionalProperties': False,
                },
                {
                    'properties': {
                        'binary': {'type': 'string'},
                        'forced_down': {'type': 'boolean'},
                        'host': {'type': 'string'},
                    },
                    'required': ['binary', 'forced_down', 'host'],
                    'additionalProperties': False,
                },
            ],
        },
    },
    'required': ['service'],
    'additionalProperties': False,
}

update_response_v253 = copy.deepcopy(update_response)
update_response_v253['properties']['service'] = copy.deepcopy(
    _service_response_v253
)
update_response_v253['properties']['service']['properties'].update({
    'forced_down': {'type': 'boolean'},
})

update_response_v269 = copy.deepcopy(update_response_v253)
update_response_v269['properties']['service'] = copy.deepcopy(
    _service_response_v269
)
update_response_v269['properties']['service']['properties'].update({
    'forced_down': {'type': 'boolean'},
})
