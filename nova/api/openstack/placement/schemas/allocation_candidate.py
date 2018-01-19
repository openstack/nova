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
"""Placement API schemas for getting allocation candidates."""

import copy


# Represents the allowed query string parameters to the GET
# /allocation_candidates API call
GET_SCHEMA_1_10 = {
    "type": "object",
    "properties": {
        "resources": {
            "type": "string"
        },
    },
    "required": [
        "resources",
    ],
    "additionalProperties": False,
}


# Add limit query parameter.
GET_SCHEMA_1_16 = copy.deepcopy(GET_SCHEMA_1_10)
GET_SCHEMA_1_16['properties']['limit'] = {
    # A query parameter is always a string in webOb, but
    # we'll handle integer here as well.
    "type": ["integer", "string"],
    "pattern": "^[1-9][0-9]*$",
    "minimum": 1,
    "minLength": 1
}

# Add required parameter.
GET_SCHEMA_1_17 = copy.deepcopy(GET_SCHEMA_1_16)
GET_SCHEMA_1_17['properties']['required'] = {
    "type": ["string"]
}
