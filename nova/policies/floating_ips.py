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


ROOT_POLICY = 'os_compute_api:os-floating-ips'
BASE_POLICY_NAME = 'os_compute_api:os-floating-ips:%s'

DEPRECATED_FIP_POLICY = policy.DeprecatedRule(
    ROOT_POLICY,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""


floating_ips_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'add',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Associate floating IPs to server. "
        " This API is deprecated.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (addFloatingIp)'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'remove',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Disassociate floating IPs to server. "
        " This API is deprecated.",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (removeFloatingIp)'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List floating IPs. This API is deprecated.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-floating-ips'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'create',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Create floating IPs. This API is deprecated.",
        operations=[
            {
                'method': 'POST',
                'path': '/os-floating-ips'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="Show floating IPs. This API is deprecated.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-floating-ips/{floating_ip_id}'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Delete floating IPs. This API is deprecated.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/os-floating-ips/{floating_ip_id}'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_FIP_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
]


def list_rules():
    return floating_ips_policies
