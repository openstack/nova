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


index_query_v20 = {
    'type': 'object',
    'properties': {
        'hidden': parameter_types.common_query_param,
        'host': parameter_types.common_query_param,
        'instance_uuid': parameter_types.common_query_param,
        'source_compute': parameter_types.common_query_param,
        'status': parameter_types.common_query_param,
        'migration_type': parameter_types.common_query_param,
    },
    # For backward compatible changes
    'additionalProperties': True
}

index_query_v259 = copy.deepcopy(index_query_v20)
index_query_v259['properties'].update({
    # The 2.59 microversion added support for paging by limit and marker
    # and filtering by changes-since.
    'limit': parameter_types.single_param(
        parameter_types.non_negative_integer),
    'marker': parameter_types.single_param({'type': 'string'}),
    'changes-since': parameter_types.single_param(
        {'type': 'string', 'format': 'date-time'}),
})
index_query_v259['additionalProperties'] = False

index_query_v266 = copy.deepcopy(index_query_v259)
index_query_v266['properties'].update({
    'changes-before': parameter_types.single_param(
        {'type': 'string', 'format': 'date-time'}),
})

index_query_v280 = copy.deepcopy(index_query_v266)
index_query_v280['properties'].update({
    # The 2.80 microversion added support for filtering migrations
    # by user_id and/or project_id
    'user_id': parameter_types.single_param({'type': 'string'}),
    'project_id': parameter_types.single_param({'type': 'string'}),
})

index_response_v20 = {
    'type': 'object',
    'properties': {
        'migrations': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'created_at': {'type': 'string', 'format': 'date-time'},
                    'dest_compute': {'type': ['string', 'null']},
                    'dest_host': {'type': ['string', 'null']},
                    'dest_node': {'type': ['string', 'null']},
                    'id': {'type': 'integer'},
                    'instance_uuid': {'type': 'string', 'format': 'uuid'},
                    'new_instance_type_id': {'type': ['integer', 'null']},
                    'old_instance_type_id': {'type': ['integer', 'null']},
                    'source_compute': {'type': ['string', 'null']},
                    'source_node': {'type': ['string', 'null']},
                    'status': {'type': 'string'},
                    'updated_at': {
                        'type': ['string', 'null'], 'format': 'date-time'
                    },
                },
                'required': [
                    'created_at',
                    'dest_compute',
                    'dest_host',
                    'dest_node',
                    'id',
                    'instance_uuid',
                    'new_instance_type_id',
                    'old_instance_type_id',
                    'source_compute',
                    'source_node',
                    'status',
                    'updated_at',
                ],
                'additionalProperties': False,
            },
        },
    },
    'required': ['migrations'],
    'additionalProperties': False,
}

index_response_v223 = copy.deepcopy(index_response_v20)
index_response_v223['properties']['migrations']['items']['properties'].update({
    'migration_type': {
        'type': 'string',
        'enum': [
            'migration', 'resize', 'live-migration', 'evacuation'
        ],
    },
    'links': response_types.links,
})
index_response_v223['properties']['migrations']['items']['required'].append(
    'migration_type'
)

index_response_v259 = copy.deepcopy(index_response_v223)
index_response_v259['properties'].update({
    'migrations_links': response_types.collection_links,
})
index_response_v259['properties']['migrations']['items']['properties'].update({
    'uuid': {'type': 'string', 'format': 'uuid'},
})
index_response_v259['properties']['migrations']['items']['required'].append(
    'uuid'
)

index_response_v280 = copy.deepcopy(index_response_v259)
index_response_v280['properties']['migrations']['items']['properties'].update({
    'project_id': parameter_types.project_id,
    'user_id': parameter_types.user_id,
})
index_response_v280['properties']['migrations']['items']['required'].extend([
    'project_id', 'user_id',
])
