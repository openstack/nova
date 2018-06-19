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


from oslo_policy import policy

from nova.api.openstack.placement.policies import base


PREFIX = 'placement:resource_providers:%s'
LIST = PREFIX % 'list'
CREATE = PREFIX % 'create'
SHOW = PREFIX % 'show'
UPDATE = PREFIX % 'update'
DELETE = PREFIX % 'delete'

rules = [
    policy.DocumentedRuleDefault(
        LIST,
        base.RULE_ADMIN_API,
        "List resource providers.",
        [
            {
                'method': 'GET',
                'path': '/resource_providers'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        CREATE,
        base.RULE_ADMIN_API,
        "Create resource provider.",
        [
            {
                'method': 'POST',
                'path': '/resource_providers'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        SHOW,
        base.RULE_ADMIN_API,
        "Show resource provider.",
        [
            {
                'method': 'GET',
                'path': '/resource_providers/{uuid}'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        UPDATE,
        base.RULE_ADMIN_API,
        "Update resource provider.",
        [
            {
                'method': 'PUT',
                'path': '/resource_providers/{uuid}'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        DELETE,
        base.RULE_ADMIN_API,
        "Delete resource provider.",
        [
            {
                'method': 'DELETE',
                'path': '/resource_providers/{uuid}'
            }
        ],
        scope_types=['system']),
]


def list_rules():
    return rules
