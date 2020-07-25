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


BASE_POLICY_NAME = 'os_compute_api:os-hosts'

POLICY_NAME = 'os_compute_api:os-hosts:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    BASE_POLICY_NAME,
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

hosts_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'list',
        check_str=base.SYSTEM_READER,
        description="""List physical hosts.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-hosts'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'show',
        check_str=base.SYSTEM_READER,
        description="""Show physical host.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'update',
        check_str=base.SYSTEM_ADMIN,
        description="""Update physical host.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-hosts/{host_name}'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'reboot',
        check_str=base.SYSTEM_ADMIN,
        description="""Reboot physical host.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/reboot'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'shutdown',
        check_str=base.SYSTEM_ADMIN,
        description="""Shutdown physical host.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/shutdown'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'start',
        check_str=base.SYSTEM_ADMIN,
        description="""Start physical host.

This API is deprecated in favor of os-hypervisors and os-services.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/startup'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
]


def list_rules():
    return hosts_policies
