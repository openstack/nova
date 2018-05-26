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


RP_TRAIT_PREFIX = 'placement:resource_providers:traits:%s'
RP_TRAIT_LIST = RP_TRAIT_PREFIX % 'list'
RP_TRAIT_UPDATE = RP_TRAIT_PREFIX % 'update'
RP_TRAIT_DELETE = RP_TRAIT_PREFIX % 'delete'

TRAITS_PREFIX = 'placement:traits:%s'
TRAITS_LIST = TRAITS_PREFIX % 'list'
TRAITS_SHOW = TRAITS_PREFIX % 'show'
TRAITS_UPDATE = TRAITS_PREFIX % 'update'
TRAITS_DELETE = TRAITS_PREFIX % 'delete'


rules = [
    policy.DocumentedRuleDefault(
        TRAITS_LIST,
        base.RULE_ADMIN_API,
        "List traits.",
        [
            {
                'method': 'GET',
                'path': '/traits'
            }
        ],
        scope_types=['system']
    ),
    policy.DocumentedRuleDefault(
        TRAITS_SHOW,
        base.RULE_ADMIN_API,
        "Show trait.",
        [
            {
                'method': 'GET',
                'path': '/traits/{name}'
            }
        ],
        scope_types=['system'],
    ),
    policy.DocumentedRuleDefault(
        TRAITS_UPDATE,
        base.RULE_ADMIN_API,
        "Update trait.",
        [
            {
                'method': 'PUT',
                'path': '/traits/{name}'
            }
        ],
        scope_types=['system'],
    ),
    policy.DocumentedRuleDefault(
        TRAITS_DELETE,
        base.RULE_ADMIN_API,
        "Delete trait.",
        [
            {
                'method': 'DELETE',
                'path': '/traits/{name}'
            }
        ],
        scope_types=['system'],
    ),
    policy.DocumentedRuleDefault(
        RP_TRAIT_LIST,
        base.RULE_ADMIN_API,
        "List resource provider traits.",
        [
            {
                'method': 'GET',
                'path': '/resource_providers/{uuid}/traits'
            }
        ],
        scope_types=['system'],
    ),
    policy.DocumentedRuleDefault(
        RP_TRAIT_UPDATE,
        base.RULE_ADMIN_API,
        "Update resource provider traits.",
        [
            {
                'method': 'PUT',
                'path': '/resource_providers/{uuid}/traits'
            }
        ],
        scope_types=['system'],
    ),
    policy.DocumentedRuleDefault(
        RP_TRAIT_DELETE,
        base.RULE_ADMIN_API,
        "Delete resource provider traits.",
        [
            {
                'method': 'DELETE',
                'path': '/resource_providers/{uuid}/traits'
            }
        ],
        scope_types=['system'],
    ),
]


def list_rules():
    return rules
