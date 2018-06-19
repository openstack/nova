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


PROVIDER_USAGES = 'placement:resource_providers:usages'
TOTAL_USAGES = 'placement:usages'


rules = [
    policy.DocumentedRuleDefault(
        PROVIDER_USAGES,
        base.RULE_ADMIN_API,
        "List resource provider usages.",
        [
            {
                'method': 'GET',
                'path': '/resource_providers/{uuid}/usages'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        # TODO(mriedem): At some point we might set scope_types=['project']
        # so that non-admin project-scoped token users can query usages for
        # their project. The context.can() target will need to change as well
        # in the actual policy enforcement check in the handler code.
        TOTAL_USAGES,
        base.RULE_ADMIN_API,
        "List total resource usages for a given project.",
        [
            {
                'method': 'GET',
                'path': '/usages'
            }
        ],
        scope_types=['system'])
]


def list_rules():
    return rules
