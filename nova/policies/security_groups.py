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


BASE_POLICY_NAME = 'os_compute_api:os-security-groups'

POLICY_NAME = 'os_compute_api:os-security-groups:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    BASE_POLICY_NAME,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

security_groups_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="""List, show, add, or remove security groups.

APIs which are directly related to security groups resource are deprecated:
Lists, shows information for, creates, updates and deletes
security groups. Creates and deletes security group rules. All these
APIs are deprecated.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-security-groups'
            },
            {
                'method': 'GET',
                'path': '/os-security-groups/{security_group_id}'
            },
            {
                'method': 'POST',
                'path': '/os-security-groups'
            },
            {
                'method': 'PUT',
                'path': '/os-security-groups/{security_group_id}'
            },
            {
                'method': 'DELETE',
                'path': '/os-security-groups/{security_group_id}'
            },
        ]),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List security groups of server.",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-security-groups'
            },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'add',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Add security groups to server.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (addSecurityGroup)'
            },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'remove',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Remove security groups from server.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (removeSecurityGroup)'
            },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return security_groups_policies
