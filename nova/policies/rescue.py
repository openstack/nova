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


BASE_POLICY_NAME = 'os_compute_api:os-rescue'
UNRESCUE_POLICY_NAME = 'os_compute_api:os-unrescue'

DEPRECATED_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-rescue',
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Rescue/Unrescue API policies are made granular with new policy
for unrescue and keeping old policy for rescue.
"""


rescue_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Rescue a server",
        operations=[
            {
                'path': '/servers/{server_id}/action (rescue)',
                'method': 'POST'
            },
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=UNRESCUE_POLICY_NAME,
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Unrescue a server",
        operations=[
            {
                'path': '/servers/{server_id}/action (unrescue)',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'
    ),
]


def list_rules():
    return rescue_policies
