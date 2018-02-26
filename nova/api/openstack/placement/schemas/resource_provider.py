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
"""Placement API schemas for resource providers."""

import copy


POST_RESOURCE_PROVIDER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 200
        },
        "uuid": {
            "type": "string",
            "format": "uuid"
        }
    },
    "required": [
        "name"
    ],
    "additionalProperties": False,
}
# Remove uuid to create the schema for PUTting a resource provider
PUT_RESOURCE_PROVIDER_SCHEMA = copy.deepcopy(POST_RESOURCE_PROVIDER_SCHEMA)
PUT_RESOURCE_PROVIDER_SCHEMA['properties'].pop('uuid')

# Placement API microversion 1.14 adds an optional parent_provider_uuid field
# to the POST and PUT request schemas
POST_RP_SCHEMA_V1_14 = copy.deepcopy(POST_RESOURCE_PROVIDER_SCHEMA)
POST_RP_SCHEMA_V1_14["properties"]["parent_provider_uuid"] = {
    "anyOf": [
        {
            "type": "string",
            "format": "uuid",
        },
        {
            "type": "null",
        }
    ]
}
PUT_RP_SCHEMA_V1_14 = copy.deepcopy(POST_RP_SCHEMA_V1_14)
PUT_RP_SCHEMA_V1_14['properties'].pop('uuid')

# Represents the allowed query string parameters to the GET /resource_providers
# API call
GET_RPS_SCHEMA_1_0 = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string"
        },
        "uuid": {
            "type": "string",
            "format": "uuid"
        }
    },
    "additionalProperties": False,
}

# Placement API microversion 1.3 adds support for a member_of attribute
GET_RPS_SCHEMA_1_3 = copy.deepcopy(GET_RPS_SCHEMA_1_0)
GET_RPS_SCHEMA_1_3['properties']['member_of'] = {
    "type": "string"
}

# Placement API microversion 1.4 adds support for requesting resource providers
# having some set of capacity for some resources. The query string is a
# comma-delimited set of "$RESOURCE_CLASS_NAME:$AMOUNT" strings. The validation
# of the string is left up to the helper code in the
# normalize_resources_qs_param() function.
GET_RPS_SCHEMA_1_4 = copy.deepcopy(GET_RPS_SCHEMA_1_3)
GET_RPS_SCHEMA_1_4['properties']['resources'] = {
    "type": "string"
}

# Placement API microversion 1.14 adds support for requesting resource
# providers within a tree of providers. The 'in_tree' query string parameter
# should be the UUID of a resource provider. The result of the GET call will
# include only those resource providers in the same "provider tree" as the
# provider with the UUID represented by 'in_tree'
GET_RPS_SCHEMA_1_14 = copy.deepcopy(GET_RPS_SCHEMA_1_4)
GET_RPS_SCHEMA_1_14['properties']['in_tree'] = {
    "type": "string",
    "format": "uuid",
}

# Microversion 1.18 adds support for the `required` query parameter to the
# `GET /resource_providers` API. It accepts a comma-separated list of string
# trait names. When specified, the API results will be filtered to include only
# resource providers marked with all the specified traits. This is in addition
# to (logical AND) any filtering based on other query parameters.
GET_RPS_SCHEMA_1_18 = copy.deepcopy(GET_RPS_SCHEMA_1_14)
GET_RPS_SCHEMA_1_18['properties']['required'] = {
    "type": "string",
}
