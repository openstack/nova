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


create = {
    'type': 'object',
    'properties': {
        'metadata': parameter_types.metadata
    },
    'required': ['metadata'],
    'additionalProperties': False,
}

metadata_update = copy.deepcopy(parameter_types.metadata)
metadata_update.update({
    'minProperties': 1,
    'maxProperties': 1
})

update = {
    'type': 'object',
    'properties': {
        'meta': metadata_update
    },
    'required': ['meta'],
    'additionalProperties': False,
}

update_all = {
    'type': 'object',
    'properties': {
        'metadata': parameter_types.metadata
    },
    'required': ['metadata'],
    'additionalProperties': False,
}
