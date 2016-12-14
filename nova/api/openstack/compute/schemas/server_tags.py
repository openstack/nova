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
from nova.objects import instance

update_all = {
    "title": "Server tags",
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": parameter_types.tag,
            "maxItems": instance.MAX_TAG_COUNT
        }
    },
    'required': ['tags'],
    'additionalProperties': False
}

update = {
    "title": "Server tag",
    "type": "null",
    'required': [],
    'additionalProperties': False
}
