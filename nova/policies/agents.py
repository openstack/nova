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


BASE_POLICY_NAME = 'os_compute_api:os-agents:%s'

DEPRECATED_AGENTS_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-agents',
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

agents_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.SYSTEM_READER,
        description="""List guest agent builds
This is XenAPI driver specific.
It is used to force the upgrade of the XenAPI guest agent on instance boot.
""",
        operations=[
            {
                'path': '/os-agents',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_AGENTS_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'create',
        check_str=base.SYSTEM_ADMIN,
        description="""Create guest agent builds
This is XenAPI driver specific.
It is used to force the upgrade of the XenAPI guest agent on instance boot.
""",
        operations=[

            {
                'path': '/os-agents',
                'method': 'POST'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_AGENTS_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'update',
        check_str=base.SYSTEM_ADMIN,
        description="""Update guest agent builds
This is XenAPI driver specific.
It is used to force the upgrade of the XenAPI guest agent on instance boot.
""",
        operations=[
            {
                'path': '/os-agents/{agent_build_id}',
                'method': 'PUT'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_AGENTS_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'delete',
        check_str=base.SYSTEM_ADMIN,
        description="""Delete guest agent builds
This is XenAPI driver specific.
It is used to force the upgrade of the XenAPI guest agent on instance boot.
""",
        operations=[
            {
                'path': '/os-agents/{agent_build_id}',
                'method': 'DELETE'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_AGENTS_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return agents_policies
