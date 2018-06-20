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
"""Reshaper schema for Placement API."""

import copy

from nova.api.openstack.placement.schemas import allocation
from nova.api.openstack.placement.schemas import common
from nova.api.openstack.placement.schemas import inventory


ALLOCATIONS = copy.deepcopy(allocation.POST_ALLOCATIONS_V1_28)
# In the reshaper we need to allow allocations to be an empty dict
# because it may be the case that there simply are no allocations
# (now) for any of the inventory being moved.
ALLOCATIONS['minProperties'] = 0
POST_RESHAPER_SCHEMA = {
    "type": "object",
    "properties": {
        "inventories": {
            "type": "object",
            "patternProperties": {
                # resource provider uuid
                common.UUID_PATTERN: inventory.PUT_INVENTORY_SCHEMA,
            },
            # We expect at least one inventories, otherwise there is no reason
            # to call the reshaper.
            "minProperties": 1,
            "additionalProperties": False,
        },
        "allocations": ALLOCATIONS,
    },
    "required": [
        "inventories",
        "allocations",
    ],
    "additionalProperties": False,
}
