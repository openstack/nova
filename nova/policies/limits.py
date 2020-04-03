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


BASE_POLICY_NAME = 'os_compute_api:limits'
OTHER_PROJECT_LIMIT_POLICY_NAME = 'os_compute_api:limits:other_project'
DEPRECATED_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-used-limits',
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

limits_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ANY,
        description="Show rate and absolute limits for the current user "
        "project",
        operations=[
            {
                'method': 'GET',
                'path': '/limits'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=OTHER_PROJECT_LIMIT_POLICY_NAME,
        check_str=base.SYSTEM_READER,
        description="""Show rate and absolute limits of other project.

This policy only checks if the user has access to the requested
project limits. And this check is performed only after the check
os_compute_api:limits passes""",
        operations=[
            {
                'method': 'GET',
                'path': '/limits'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return limits_policies
