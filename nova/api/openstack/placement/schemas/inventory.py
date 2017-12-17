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
"""Inventory schemas for Placement API."""

import copy

from nova import db


RESOURCE_CLASS_IDENTIFIER = "^[A-Z0-9_]+$"
BASE_INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "resource_provider_generation": {
            "type": "integer"
        },
        "total": {
            "type": "integer",
            "maximum": db.MAX_INT,
            "minimum": 1,
        },
        "reserved": {
            "type": "integer",
            "maximum": db.MAX_INT,
            "minimum": 0,
        },
        "min_unit": {
            "type": "integer",
            "maximum": db.MAX_INT,
            "minimum": 1
        },
        "max_unit": {
            "type": "integer",
            "maximum": db.MAX_INT,
            "minimum": 1
        },
        "step_size": {
            "type": "integer",
            "maximum": db.MAX_INT,
            "minimum": 1
        },
        "allocation_ratio": {
            "type": "number",
            "maximum": db.SQL_SP_FLOAT_MAX
        },
    },
    "required": [
        "total",
        "resource_provider_generation"
    ],
    "additionalProperties": False
}


POST_INVENTORY_SCHEMA = copy.deepcopy(BASE_INVENTORY_SCHEMA)
POST_INVENTORY_SCHEMA['properties']['resource_class'] = {
    "type": "string",
    "pattern": RESOURCE_CLASS_IDENTIFIER,
}
POST_INVENTORY_SCHEMA['required'].append('resource_class')
POST_INVENTORY_SCHEMA['required'].remove('resource_provider_generation')


PUT_INVENTORY_RECORD_SCHEMA = copy.deepcopy(BASE_INVENTORY_SCHEMA)
PUT_INVENTORY_RECORD_SCHEMA['required'].remove('resource_provider_generation')
PUT_INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "resource_provider_generation": {
            "type": "integer"
        },
        "inventories": {
            "type": "object",
            "patternProperties": {
                RESOURCE_CLASS_IDENTIFIER: PUT_INVENTORY_RECORD_SCHEMA,
            }
        }
    },
    "required": [
        "resource_provider_generation",
        "inventories"
    ],
    "additionalProperties": False
}
