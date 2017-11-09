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

from nova.api.validation import parameter_types

list_query_schema_v20 = {
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
    # TODO(mriedem): In a future microversion, consider changing
    # additionalProperties to False, remove the 'hidden' filter since
    # it's vestigial, and enforce type and enum checks for the filters
    # where that makes sense, e.g. instance_uuid, status and migration_type.
    'additionalProperties': True
}
