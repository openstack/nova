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


BASE_POLICY_NAME = 'os_compute_api:os-attach-interfaces'
POLICY_ROOT = 'os_compute_api:os-attach-interfaces:%s'
DEPRECATED_INTERFACES_POLICY = policy.DeprecatedRule(
    BASE_POLICY_NAME,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

attach_interfaces_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List port interfaces attached to a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-interface'
            },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INTERFACES_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="Show details of a port interface attached to a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-interface/{port_id}'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INTERFACES_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Attach an interface to a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/os-interface'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INTERFACES_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Detach an interface from a server",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/os-interface/{port_id}'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INTERFACES_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0')
]


def list_rules():
    return attach_interfaces_policies
