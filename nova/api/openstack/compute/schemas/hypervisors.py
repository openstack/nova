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

_hypervisor_detail_response = {
    'type': 'object',
    'properties': {
        'cpu_info': {'type': 'string'},
        'current_workload': {'type': ['null', 'integer']},
        'disk_available_least': {'type': ['null', 'integer']},
        'free_disk_gb': {'type': ['null', 'integer']},
        'free_ram_mb': {'type': ['null', 'integer']},
        'host_ip': {'type': ['null', 'string']},
        'hypervisor_hostname': {'type': 'string'},
        'hypervisor_type': {'type': 'string'},
        'hypervisor_version': {'type': ['string', 'integer']},
        'id': {'type': 'integer'},
        'local_gb': {'type': 'integer'},
        'local_gb_used': {'type': 'integer'},
        'memory_mb': {'type': 'integer'},
        'memory_mb_used': {'type': 'integer'},
        'running_vms': {'type': ['null', 'integer']},
        'service': {
            'type': 'object',
            'properties': {
                'disabled_reason': {'type': ['null', 'string']},
                'host': {'type': 'string'},
                'id': {'type': 'integer'},
            },
            'required': ['disabled_reason', 'host', 'id'],
        },
        'state': {'enum': ['up', 'down']},
        'status': {'enum': ['enabled', 'disabled']},
        'vcpus': {'type': 'integer'},
        'vcpus_used': {'type': 'integer'},
    },
    'required': [
        'cpu_info',
        'current_workload',
        'free_disk_gb',
        'free_ram_mb',
        'host_ip',
        'hypervisor_hostname',
        'hypervisor_type',
        'hypervisor_version',
        'id',
        'local_gb',
        'local_gb_used',
        'memory_mb',
        'memory_mb_used',
        'running_vms',
        'service',
        'state',
        'status',
        'vcpus',
        'vcpus_used',
    ],
    'additionalProperties': False,
}

_hypervisor_detail_response_v228 = copy.deepcopy(_hypervisor_detail_response)
_hypervisor_detail_response_v228['properties'].update({
    'cpu_info': {
        # NOTE(stephenfin): This is virt-driver specific hence no schema
        'type': 'object',
        'properties': {},
        'required': [],
        'additionalProperties': True,
    },
})

_hypervisor_detail_response_v253 = copy.deepcopy(
    _hypervisor_detail_response_v228
)
_hypervisor_detail_response_v253['properties'].update({
    'id': {'type': 'string', 'format': 'uuid'},
    'servers': copy.deepcopy(_servers_response),
})
_hypervisor_detail_response_v253['properties']['service'][
    'properties'
].update({
    'id': {'type': 'string', 'format': 'uuid'},
})

_hypervisor_detail_response_v288 = copy.deepcopy(
    _hypervisor_detail_response_v253
)
for field in {
    'cpu_info',
    'current_workload',
    'free_disk_gb',
    'free_ram_mb',
    'local_gb',
    'local_gb_used',
    'memory_mb',
    'memory_mb_used',
    'running_vms',
    'vcpus',
    'vcpus_used',
}:
    del _hypervisor_detail_response_v288['properties'][field]
    _hypervisor_detail_response_v288['required'].remove(field)

_hypervisor_detail_response_v288['properties'].update({
    'uptime': {'type': ['string', 'null']}
})
_hypervisor_detail_response_v288['required'].append('uptime')

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
# v2.75 makes the 'servers' property always present even if empty *unless* the
# 'with_servers' query parameter is 'false'. This dependency between a query
# parameter and a response parameter is not something we can capture with
# jsonschema and we can't update 'required' as a result
index_response_v253 = copy.deepcopy(index_response_v233)
index_response_v253['properties']['hypervisors']['items'] = (
    _hypervisor_response_v253
)

search_response = copy.deepcopy(index_response)

servers_response = copy.deepcopy(index_response)
servers_response['properties']['hypervisors']['items']['properties'].update({
    'servers': copy.deepcopy(_servers_response),
})

detail_response = copy.deepcopy(index_response)
detail_response['properties']['hypervisors'][
    'items'
] = _hypervisor_detail_response

# v2.28 changes the 'cpu_info' field from a stringified object to a real object
detail_response_v228 = copy.deepcopy(detail_response)
detail_response_v228['properties']['hypervisors'][
    'items'
] = _hypervisor_detail_response_v228

# v2.33 adds the hypervisors_links field
detail_response_v233 = copy.deepcopy(detail_response_v228)
detail_response_v233['properties'].update({
    'hypervisors_links': response_types.collection_links,
})

# v2.53 adds the 'servers' field but only if a user requests it via the
# 'with_servers' query arg. It also changes the 'id' field to a UUID. Note that
# v2.75 makes the 'servers' property always present even if empty *unless* the
# 'with_servers' query parameter is 'false'. This dependency between a query
# parameter and a response parameter is not something we can capture with
# jsonschema and we can't update 'required' as a result
detail_response_v253 = copy.deepcopy(detail_response_v233)
detail_response_v253['properties']['hypervisors'][
    'items'
] = _hypervisor_detail_response_v253

# v2.88 drops a whole lot of fields that were now duplicated in placement. It
# also adds the uptime field into the response rather than a separate API
detail_response_v288 = copy.deepcopy(detail_response_v253)
detail_response_v288['properties']['hypervisors'][
    'items'
] = _hypervisor_detail_response_v288

show_response = {
    'type': 'object',
    'properties': {
        'hypervisor': copy.deepcopy(_hypervisor_detail_response),
    },
    'required': ['hypervisor'],
    'additionalProperties': False,
}

show_response_v228 = copy.deepcopy(show_response)
show_response_v228['properties']['hypervisor'] = copy.deepcopy(
    _hypervisor_detail_response_v228
)

show_response_v253 = copy.deepcopy(show_response_v228)
show_response_v253['properties']['hypervisor'] = copy.deepcopy(
    _hypervisor_detail_response_v253
)

show_response_v288 = copy.deepcopy(show_response_v253)
show_response_v288['properties']['hypervisor'] = copy.deepcopy(
    _hypervisor_detail_response_v288
)

uptime_response = {
    'type': 'object',
    'properties': {
        'hypervisor': copy.deepcopy(_hypervisor_response),
    },
    'required': ['hypervisor'],
    'additionalProperties': False,
}
uptime_response['properties']['hypervisor']['properties'].update({
    'uptime': {'type': ['string', 'null']}
})
uptime_response['properties']['hypervisor']['required'].append('uptime')

uptime_response_v253 = copy.deepcopy(uptime_response)
uptime_response_v253['properties']['hypervisor'] = copy.deepcopy(
    _hypervisor_response_v253
)
uptime_response_v253['properties']['hypervisor']['properties'].update({
    'uptime': {'type': ['string', 'null']}
})
uptime_response_v253['properties']['hypervisor']['required'].append('uptime')

statistics_response = {
    'type': 'object',
    'properties': {
        'hypervisor_statistics': {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer'},
                'current_workload': {'type': ['null', 'integer']},
                'disk_available_least': {'type': ['null', 'integer']},
                'free_disk_gb': {'type': ['null', 'integer']},
                'free_ram_mb': {'type': ['null', 'integer']},
                'local_gb': {'type': 'integer'},
                'local_gb_used': {'type': 'integer'},
                'memory_mb': {'type': 'integer'},
                'memory_mb_used': {'type': 'integer'},
                'running_vms': {'type': ['null', 'integer']},
                'vcpus': {'type': 'integer'},
                'vcpus_used': {'type': 'integer'},
            },
            'required': [
                'count',
                'current_workload',
                'disk_available_least',
                'free_disk_gb',
                'free_ram_mb',
                'local_gb',
                'local_gb_used',
                'memory_mb',
                'memory_mb_used',
                'running_vms',
                'vcpus',
                'vcpus_used',
            ],
            'additionalProperties': False,
        },
    },
    'required': ['hypervisor_statistics'],
    'additionalProperties': False,
}
