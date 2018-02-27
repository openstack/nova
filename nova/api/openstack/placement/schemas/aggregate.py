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
"""Aggregate schemas for Placement API."""
import copy


_AGGREGATES_LIST_SCHEMA = {
    "type": "array",
    "items": {
        "type": "string",
        "format": "uuid"
    },
    "uniqueItems": True
}


PUT_AGGREGATES_SCHEMA_V1_1 = copy.deepcopy(_AGGREGATES_LIST_SCHEMA)


PUT_AGGREGATES_SCHEMA_V1_19 = {
    "type": "object",
    "properties": {
        "aggregates": copy.deepcopy(_AGGREGATES_LIST_SCHEMA),
        "resource_provider_generation": {
            "type": "integer",
        }
    },
    "required": [
        "aggregates",
        "resource_provider_generation",
    ],
    "additionalProperties": False,
}
