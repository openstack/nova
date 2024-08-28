# Copyright 2017 Huawei Technologies Co.,LTD.
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

index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_query_v233 = {
    'type': 'object',
    'properties': parameter_types.pagination_parameters,
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.53, the additional parameters
    # are not allowed.
    'additionalProperties': True
}

index_query_v253 = {
    'type': 'object',
    'properties': {
        # The 2.33 microversion added support for paging by limit and marker.
        'limit': parameter_types.single_param(
            parameter_types.non_negative_integer),
        'marker': parameter_types.single_param({'type': 'string'}),
        # The 2.53 microversion adds support for filtering by hostname pattern
        # and requesting hosted servers in the GET /os-hypervisors and
        # GET /os-hypervisors/detail response.
        'hypervisor_hostname_pattern': parameter_types.single_param(
            parameter_types.fqdn),
        'with_servers': parameter_types.single_param(
            parameter_types.boolean)
    },
    'additionalProperties': False
}

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

show_query_v253 = {
    'type': 'object',
    'properties': {
        'with_servers': parameter_types.single_param(
            parameter_types.boolean)
    },
    'additionalProperties': False
}

# NOTE(stephenfin): These schemas are intentionally empty since these APIs are
# deprecated
statistics_query = {}
search_query = {}
servers_query = {}
uptime_query = {}

_servers_response = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string'},
            'uuid': {'type': 'string', 'format': 'uuid'},
        },
        'required': ['name', 'uuid'],
        'additionalProperties': False,
    },
}

_hypervisor_response = {
    'type': 'object',
    'properties': {
        'id': {'type': 'integer'},
        'hypervisor_hostname': {'type': 'string'},
        'state': {'enum': ['up', 'down']},
        'status': {'enum': ['enabled', 'disabled']},
    },
    'required': ['id', 'hypervisor_hostname', 'state', 'status'],
    'additionalProperties': False,
}

_hypervisor_response_v253 = copy.deepcopy(_hypervisor_response)
_hypervisor_response_v253['properties'].update({
    'id': {'type': 'string', 'format': 'uuid'},
    'servers': copy.deepcopy(_servers_response),
})

index_response = {
    'type': 'object',
    'properties': {
        'hypervisors': {
            'type': 'array',
            'items': copy.deepcopy(_hypervisor_response),
        },
    },
    'required': ['hypervisors'],
    'additionalProperties': False,
}

# v2.33 adds the hypervisors_links field
index_response_v233 = copy.deepcopy(index_response)
index_response_v233['properties'].update({
    'hypervisors_links': response_types.collection_links,
})

# v2.53 adds the 'servers' field but only if a user requests it via the
# 'with_servers' query arg. It also changes the 'id' field to a UUID. Note that
# v2.75 makes the 'servers' property always present even if empty, but that's
# not something we can capture with jsonschema so we don't try
index_response_v253 = copy.deepcopy(index_response_v233)
index_response_v253['properties']['hypervisors']['items'] = (
    _hypervisor_response_v253
)

search_response = copy.deepcopy(index_response)

servers_response = copy.deepcopy(index_response)
servers_response['properties']['hypervisors']['items']['properties'].update({
    'servers': copy.deepcopy(_servers_response),
})
