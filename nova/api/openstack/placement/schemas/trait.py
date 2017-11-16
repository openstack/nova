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
"""Trait schemas for Placement API."""

import copy

TRAIT = {
    "type": "string",
    'minLength': 1, 'maxLength': 255,
}

CUSTOM_TRAIT = copy.deepcopy(TRAIT)
CUSTOM_TRAIT.update({"pattern": "^CUSTOM_[A-Z0-9_]+$"})

PUT_TRAITS_SCHEMA = {
    "type": "object",
    "properties": {
        "traits": {
            "type": "array",
            "items": CUSTOM_TRAIT,
        }
    },
    'required': ['traits'],
    'additionalProperties': False
}

SET_TRAITS_FOR_RP_SCHEMA = copy.deepcopy(PUT_TRAITS_SCHEMA)
SET_TRAITS_FOR_RP_SCHEMA['properties']['traits']['items'] = TRAIT
SET_TRAITS_FOR_RP_SCHEMA['properties'][
    'resource_provider_generation'] = {'type': 'integer'}
SET_TRAITS_FOR_RP_SCHEMA['required'].append('resource_provider_generation')

LIST_TRAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string"
        },
        "associated": {
            "type": "string",
        }
    },
    "additionalProperties": False
}
