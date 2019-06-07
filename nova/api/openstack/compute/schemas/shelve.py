# Copyright 2019 INSPUR Corporation.  All rights reserved.
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

# NOTE(brinzhang): For older microversion there will be no change as
# schema is applied only for >2.77 with unshelve a server API.
# Anything working in old version keep working as it is.
unshelve_v277 = {
    'type': 'object',
    'properties': {
        'unshelve': {
            'type': ['object', 'null'],
            'properties': {
                'availability_zone': parameter_types.name
            },
            # NOTE: The allowed request body is {'unshelve': null} or
            # {'unshelve': {'availability_zone': <string>}}, not allowed
            # {'unshelve': {}} as the request body for unshelve.
            'required': ['availability_zone'],
            'additionalProperties': False,
        },
    },
    'required': ['unshelve'],
    'additionalProperties': False,
}
