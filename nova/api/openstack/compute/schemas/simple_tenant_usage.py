# Copyright 2017 NEC Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from nova.api.validation import parameter_types
from nova.api.validation import response_types
from nova.compute import vm_states


index_query = {
    'type': 'object',
    'properties': {
        'start': parameter_types.multi_params({'type': 'string'}),
        'end': parameter_types.multi_params({'type': 'string'}),
        'detailed': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

show_query = {
    'type': 'object',
    'properties': {
        'start': parameter_types.multi_params({'type': 'string'}),
        'end': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_v240 = copy.deepcopy(index_query)
index_query_v240['properties'].update(
    parameter_types.pagination_parameters)

show_query_v240 = copy.deepcopy(show_query)
show_query_v240['properties'].update(
    parameter_types.pagination_parameters)

index_query_v275 = copy.deepcopy(index_query_v240)
index_query_v275['additionalProperties'] = False

show_query_v275 = copy.deepcopy(show_query_v240)
show_query_v275['additionalProperties'] = False

_server_usage_response = {
    'type': 'object',
    'properties': {
        'ended_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'flavor': {'type': 'string'},
        'hours': {'type': 'number'},
        'instance_id': {'type': 'string', 'format': 'uuid'},
        'local_gb': {'type': 'integer', 'minimum': 0},
        'memory_mb': {'type': 'integer', 'minimum': 1},
        'name': {'type': 'string'},
        'started_at': {'type': 'string', 'format': 'date-time'},
        'state': {
            'type': 'string',
            'enum': [
                vm_states.ACTIVE,
                vm_states.BUILDING,
                # vm_states.DELETED is ignored in favour of 'terminated'
                vm_states.ERROR,
                vm_states.PAUSED,
                vm_states.RESCUED,
                vm_states.RESIZED,
                vm_states.SHELVED,
                vm_states.SHELVED_OFFLOADED,
                # vm_states.SOFT_DELETED is ignored in favour of 'terminated'
                vm_states.STOPPED,
                vm_states.SUSPENDED,
                'terminated',
            ],
        },
        'tenant_id': parameter_types.project_id,
        'uptime': {'type': 'integer', 'minimum': 0},
        'vcpus': {'type': 'integer', 'minimum': 1},
    },
    'required': [
        # local_gb, memory_mb and vcpus can be omitted if the instance is not
        # found
        'ended_at',
        'flavor',
        'hours',
        'instance_id',
        'name',
        'state',
        'started_at',
        'tenant_id',
        'uptime',
    ],
    'additionalProperties': False,
}

_usage_response = {
    'type': 'object',
    'properties': {
        'server_usages': {
            'type': 'array',
            'items': _server_usage_response,
        },
        'start': {'type': 'string', 'format': 'date-time'},
        'stop': {'type': 'string', 'format': 'date-time'},
        'tenant_id': parameter_types.project_id,
        # these are number instead of integer since the underlying values are
        # floats after multiplication by hours (a float)
        'total_hours': {'type': 'number', 'minimum': 0},
        'total_local_gb_usage': {'type': 'number', 'minimum': 0},
        'total_memory_mb_usage': {'type': 'number', 'minimum': 0},
        'total_vcpus_usage': {'type': 'number', 'minimum': 0},
    },
    'required': [
        'start',
        'stop',
        'tenant_id',
        'total_hours',
        'total_local_gb_usage',
        'total_memory_mb_usage',
        'total_vcpus_usage',
    ],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        'tenant_usages': {
            'type': 'array',
            'items': _usage_response,
        },
    },
    'required': ['tenant_usages'],
    'additionalProperties': False,
}

index_response_v240 = copy.deepcopy(index_response)
index_response_v240['properties']['tenant_usages_links'] = (
    response_types.collection_links
)

show_response = {
    'type': 'object',
    # if there are no usages for the tenant, we return an empty object rather
    # than an object with all zero values, thus, oneOf
    'properties': {
        'tenant_usage': {
            'oneOf': [
                copy.deepcopy(_usage_response),
                {
                    'type': 'object',
                    'properties': {},
                    'required': [],
                    'additionalProperties': False,
                },
            ],
        },
    },
    'required': ['tenant_usage'],
    'additionalProperties': False,
}
show_response['properties']['tenant_usage']['oneOf'][0]['required'].append(
    'server_usages'
)

show_response_v240 = copy.deepcopy(show_response)
show_response_v240['properties']['tenant_usage_links'] = (
    response_types.collection_links
)
