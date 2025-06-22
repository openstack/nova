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


POLICY_ROOT = 'os_compute_api:servers:migrations:%s'

DEPRECATED_REASON = """\
Nova introduces one new policy to list live migrations. The original policy
is not deprecated and used to list the in-progress live migration without
host info. A new policy is added to list live migration with host info.
If you have overridden the original policy in your deployment, you must
also update the new policy to keep the same permissions.
"""

DEPRECATED_POLICY = policy.DeprecatedRule(
    POLICY_ROOT % 'index',
    base.ADMIN,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='32.0.0'
)

servers_migrations_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.ADMIN,
        description="Show details for an in-progress live migration for a "
        "given server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'force_complete',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="Force an in-progress live migration for a given server "
        "to complete",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/migrations/{migration_id}'
                        '/action (force_complete)'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="Delete(Abort) an in-progress live migration",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ],
        scope_types=['project']),

    # NOTE(gmaan): You might see this policy as deprecated in the new policy
    # 'index:host' but it is not deprecated and still be used to list the live
    # migration without host info. By adding this existing policy in new
    # policy deprecated field, oslo.policy will handle the policy overridden
    # case. In that case, oslo.policy will pick the existing policy overridden
    # value from policy.yaml file and apply the same to the new policy. This
    # way existing deployment (for default as well as custom policy case) will
    # not break.
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="Lists in-progress live migrations for a given server "
        "without host info.",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index:host',
        check_str=base.ADMIN,
        description="Lists in-progress live migrations for a given server "
        "with host info.",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations'
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
    return servers_migrations_policies
