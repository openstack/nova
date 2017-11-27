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
from nova.api.validation import parameter_types

index_query = {
    'type': 'object',
    'properties': {
        'limit': parameter_types.multi_params(
             parameter_types.non_negative_integer),
        'marker': parameter_types.multi_params({'type': 'string'}),
        'is_public': parameter_types.multi_params({'type': 'string'}),
        'minRam': parameter_types.multi_params({'type': 'string'}),
        'minDisk': parameter_types.multi_params({'type': 'string'}),
        'sort_key': parameter_types.multi_params({'type': 'string'}),
        'sort_dir': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In the future, we may block the additional parameters
    # by bump in Microversion.
    'additionalProperties': True
}
