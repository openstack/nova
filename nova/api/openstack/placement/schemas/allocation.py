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
"""Placement API schemas for setting and deleting allocations."""

import copy


ALLOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "allocations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "resource_provider": {
                        "type": "object",
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "format": "uuid"
                            }
                        },
                        "additionalProperties": False,
                        "required": ["uuid"]
                    },
                    "resources": {
                        "type": "object",
                        "minProperties": 1,
                        "patternProperties": {
                            "^[0-9A-Z_]+$": {
                                "type": "integer",
                                "minimum": 1,
                            }
                        },
                        "additionalProperties": False
                    }
                },
                "required": [
                    "resource_provider",
                    "resources"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["allocations"],
    "additionalProperties": False
}

ALLOCATION_SCHEMA_V1_8 = copy.deepcopy(ALLOCATION_SCHEMA)
ALLOCATION_SCHEMA_V1_8['properties']['project_id'] = {'type': 'string',
                                                      'minLength': 1,
                                                      'maxLength': 255}
ALLOCATION_SCHEMA_V1_8['properties']['user_id'] = {'type': 'string',
                                                   'minLength': 1,
                                                   'maxLength': 255}
ALLOCATION_SCHEMA_V1_8['required'].extend(['project_id', 'user_id'])

# Update the allocation schema to achieve symmetry with the representation
# used when GET /allocations/{consumer_uuid} is called.
# NOTE(cdent): Explicit duplication here for sake of comprehensibility.
ALLOCATION_SCHEMA_V1_12 = {
    "type": "object",
    "properties": {
        "allocations": {
            "type": "object",
            "minProperties": 1,
            # resource provider uuid
            "patternProperties": {
                "^[0-9a-fA-F-]{36}$": {
                    "type": "object",
                    "properties": {
                        # generation is optional
                        "generation": {
                            "type": "integer",
                        },
                        "resources": {
                            "type": "object",
                            "minProperties": 1,
                            # resource class
                            "patternProperties": {
                                "^[0-9A-Z_]+$": {
                                    "type": "integer",
                                    "minimum": 1,
                                }
                            },
                            "additionalProperties": False
                        }
                    },
                    "required": ["resources"],
                    "additionalProperties": False
                }
            },
            "additionalProperties": False
        },
        "project_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255
        },
        "user_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255
        }
    },
    "additionalProperties": False,
    "required": [
        "allocations",
        "project_id",
        "user_id"
    ]
}


# POST to /allocations, added in microversion 1.13, uses the
# POST_ALLOCATIONS_V1_13 schema to allow multiple allocations
# from multiple consumers in one request. It is a dict, keyed by
# consumer uuid, using the form of PUT allocations from microversion
# 1.12. In POST the allocations can be empty, so DELETABLE_ALLOCATIONS
# modifies ALLOCATION_SCHEMA_V1_12 accordingly.
DELETABLE_ALLOCATIONS = copy.deepcopy(ALLOCATION_SCHEMA_V1_12)
DELETABLE_ALLOCATIONS['properties']['allocations']['minProperties'] = 0
POST_ALLOCATIONS_V1_13 = {
    "type": "object",
    "minProperties": 1,
    "additionalProperties": False,
    "patternProperties": {
        "^[0-9a-fA-F-]{36}$": DELETABLE_ALLOCATIONS
    }
}

# A required consumer generation was added to the top-level dict in this
# version of PUT /allocations/{consumer_uuid}. In addition, the PUT
# /allocations/{consumer_uuid}/now allows for empty allocations (indicating the
# allocations are being removed)
ALLOCATION_SCHEMA_V1_28 = copy.deepcopy(DELETABLE_ALLOCATIONS)
ALLOCATION_SCHEMA_V1_28['properties']['consumer_generation'] = {
    "type": ["integer", "null"],
    "additionalProperties": False
}
ALLOCATION_SCHEMA_V1_28['required'].append("consumer_generation")

# A required consumer generation was added to the allocations dicts in this
# version of POST /allocations
REQUIRED_GENERATION_ALLOCS_POST = copy.deepcopy(DELETABLE_ALLOCATIONS)
alloc_props = REQUIRED_GENERATION_ALLOCS_POST['properties']
alloc_props['consumer_generation'] = {
    "type": ["integer", "null"],
    "additionalProperties": False
}
REQUIRED_GENERATION_ALLOCS_POST['required'].append("consumer_generation")
POST_ALLOCATIONS_V1_28 = copy.deepcopy(POST_ALLOCATIONS_V1_13)
POST_ALLOCATIONS_V1_28["patternProperties"] = {
    "^[0-9a-fA-F-]{36}$": REQUIRED_GENERATION_ALLOCS_POST
}
