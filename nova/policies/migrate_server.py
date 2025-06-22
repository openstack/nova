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


POLICY_ROOT = 'os_compute_api:os-migrate-server:%s'

DEPRECATED_REASON = """\
Nova introduces one more policy to live migration API. The original policy is
not deprecated and used to allow live migration without requesting a specific
host. A new policy is added to control the live migration requesting a
specific host. If you have overridden the original policy in your deployment,
you must also add the new policy to keep the same permissions for live
migration to a specific host.
"""

DEPRECATED_POLICY = policy.DeprecatedRule(
    POLICY_ROOT % 'migrate_live',
    base.ADMIN,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='32.0.0'
)

migrate_server_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'migrate',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="Cold migrate a server without specifying a host",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (migrate)'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'migrate:host',
        check_str=base.ADMIN,
        description="Cold migrate a server to a specified host",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (migrate)'
            }
        ],
        scope_types=['project']),

    # NOTE(gmaan): You might see this policy as deprecated in the new policy
    # 'migrate_live:host' but it is not deprecated and still be used for
    # the live migration without specifying a host. By adding this existing
    # policy in new policy deprecated field, oslo.policy will handle the policy
    # overridden case. In that case, oslo.policy will pick the existing policy
    # overridden value from policy.yaml file and apply the same to the new
    # policy. This way existing deployment (for default as well as custom
    # policy case) will not break.
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'migrate_live',
        check_str=base.PROJECT_MANAGER_OR_ADMIN,
        description="Live migrate a server to a new host without a reboot "
        "without specifying a host.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-migrateLive)'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'migrate_live:host',
        check_str=base.ADMIN,
        description="Live migrate a server to a specified host without "
        "a reboot.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-migrateLive)'
            }
        ],
        scope_types=['project'],
        # TODO(gmaan): We can remove this after the next SLURP release
        # (after 2026.1 release). We need to keep this deprecated rule
        # for the case where operator has overridden the old policy
        # 'migrate_live' in policy.yaml. For details, refer to the above
        # comment in the 'migrate_live' policy rule.
        deprecated_rule=DEPRECATED_POLICY),
]


def list_rules():
    return migrate_server_policies
