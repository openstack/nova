# Copyright 2017 NEC Corporation.  All rights reserved.
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

# NOTE(takashin): The following sort keys are defined for backward
# compatibility. If they are changed, the API microversion should be bumped.
VALID_SORT_KEYS = [
    'created_at', 'description', 'disabled', 'ephemeral_gb', 'flavorid', 'id',
    'is_public', 'memory_mb', 'name', 'root_gb', 'rxtx_factor', 'swap',
    'updated_at', 'vcpu_weight', 'vcpus'
]

VALID_SORT_DIR = ['asc', 'desc']

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'marker': parameter_types.multi_params({'type': 'string'}),
        'is_public': parameter_types.multi_params({'type': 'string'}),
        'minRam': parameter_types.multi_params({'type': 'string'}),
        'minDisk': parameter_types.multi_params({'type': 'string'}),
        'sort_key': parameter_types.multi_params({'type': 'string',
                                                  'enum': VALID_SORT_KEYS}),
        'sort_dir': parameter_types.multi_params({'type': 'string',
                                                  'enum': VALID_SORT_DIR})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_275 = copy.deepcopy(index_query)
index_query_275['additionalProperties'] = False
