#   Copyright 2023 SAP SE
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
from nova.api.validation import parameter_types

in_cluster_vmotion = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'instance_uuid': parameter_types.server_id,
        'host': {
            'pattern': '^host-[0-9]+$',
            'type': 'string'
        }
    },
    'required': ['instance_uuid', 'host'],
    'additionalProperties': False,
}

usage_by_az_query_params = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'project_id': parameter_types.single_param(parameter_types.project_id),
    },
    'required': ['project_id'],
    'additionalProperties': False,
}
