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


BASE_POLICY_NAME = 'os_compute_api:os-hypervisors:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-hypervisors',
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

hypervisors_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.SYSTEM_READER,
        description="List all hypervisors.",
        operations=[
            {
                'path': '/os-hypervisors',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list-detail',
        check_str=base.SYSTEM_READER,
        description="List all hypervisors with details",
        operations=[
            {
                'path': '/os-hypervisors/details',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'statistics',
        check_str=base.SYSTEM_READER,
        description="Show summary statistics for all hypervisors "
        "over all compute nodes.",
        operations=[
            {
                'path': '/os-hypervisors/statistics',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'show',
        check_str=base.SYSTEM_READER,
        description="Show details for a hypervisor.",
        operations=[
            {
                'path': '/os-hypervisors/{hypervisor_id}',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'uptime',
        check_str=base.SYSTEM_READER,
        description="Show the uptime of a hypervisor.",
        operations=[
            {
                'path': '/os-hypervisors/{hypervisor_id}/uptime',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'search',
        check_str=base.SYSTEM_READER,
        description="Search hypervisor by hypervisor_hostname pattern.",
        operations=[
            {
                'path': '/os-hypervisors/{hypervisor_hostname_pattern}/search',
                'method': 'GET'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'servers',
        check_str=base.SYSTEM_READER,
        description="List all servers on hypervisors that can match "
        "the provided hypervisor_hostname pattern.",
        operations=[
            {
                'path':
                '/os-hypervisors/{hypervisor_hostname_pattern}/servers',
                'method': 'GET'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0',
    ),
]


def list_rules():
    return hypervisors_policies
