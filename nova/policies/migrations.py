# Copyright 2016 Cloudbase Solutions Srl
# All Rights Reserved.
#
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

from nova.policies import base


POLICY_ROOT = 'os_compute_api:os-migrations:%s'

DEPRECATED_REASON = """\
Nova introduces two new policies to list migrations. The original policy
is not deprecated and used to list the live migration without host info.
Two new policies are added to list migration with host info and cross
projects migrations. If you have overridden the original policy in your
deployment, you must also update the new policy to keep the same
permissions.
"""

DEPRECATED_POLICY = policy.DeprecatedRule(
    POLICY_ROOT % 'index',
    base.ADMIN,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='32.0.0'
)


migrations_policies = [
    # NOTE(gmaan): You might see this policy as deprecated in the new policies
    # 'index:all_projects' and 'index:host' but it is not deprecated and still
    # be used to list the migration without host info. By adding this existing
    # policy in new policies deprecated field, oslo.policy will handle the
    # policy overridden case. In that case, oslo.policy will pick the existing
    # policy overridden value from policy.yaml file and apply the same to the
    # new policy. This way existing deployment (for default as well as custom
    # policy case) will not break.
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="List migrations without host info",
        operations=[
            {
                'method': 'GET',
                'path': '/os-migrations'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index:all_projects',
        check_str=base.ADMIN,
        description="List migrations for all or cross projects",
        operations=[
            {
                'method': 'GET',
                'path': '/os-migrations'
            }
        ],
        scope_types=['project'],
        # TODO(gmaan): We can remove this after the next SLURP release
        # (after 2026.1 release). We need to keep this deprecated rule
        # for the case where operator has overridden the old policy
        # 'index' in policy.yaml. For details, refer to the above
        # comment in the 'index' policy rule.
        deprecated_rule=DEPRECATED_POLICY),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index:host',
        check_str=base.ADMIN,
        description="List migrations with host info",
        operations=[
            {
                'method': 'GET',
                'path': '/os-migrations'
            }
        ],
        scope_types=['project'],
        # TODO(gmaan): We can remove this after the next SLURP release
        # (after 2026.1 release). We need to keep this deprecated rule
        # for the case where operator has overridden the old policy
        # 'index' in policy.yaml. For details, refer to the above
        # comment in the 'index' policy rule.
        deprecated_rule=DEPRECATED_POLICY),
]


def list_rules():
    return migrations_policies
