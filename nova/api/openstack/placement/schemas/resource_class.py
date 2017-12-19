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
"""Placement API schemas for resource classes."""

import copy


POST_RC_SCHEMA_V1_2 = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "pattern": "^CUSTOM\_[A-Z0-9_]+$",
            "maxLength": 255,
        },
    },
    "required": [
        "name"
    ],
    "additionalProperties": False,
}
PUT_RC_SCHEMA_V1_2 = copy.deepcopy(POST_RC_SCHEMA_V1_2)
