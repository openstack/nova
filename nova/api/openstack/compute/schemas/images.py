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

# NOTE(stephenfin): These schemas are incomplete but won't be enhanced further
# since these APIs have been removed

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_query = {
    'type': 'object',
    'properties': {
        # NOTE(stephenfin): We never validated these and we're not going to add
        # that validation now.
        # field filters
        'name': {},
        'status': {},
        'changes-since': {},
        'server': {},
        'type': {},
        'minRam': {},
        'minDisk': {},
        # pagination filters
        'limit': parameter_types.multi_params(
            parameter_types.positive_integer),
        'page_size': parameter_types.multi_params(
            parameter_types.positive_integer),
        'marker': {},
        'offset': parameter_types.multi_params(
            parameter_types.positive_integer),
    },
    'patternProperties': {
        '^property-.*$': {},
    },
    'additionalProperties': True,
}

detail_query = index_query
