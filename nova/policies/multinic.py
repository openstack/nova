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


ROOT_POLICY = 'os_compute_api:os-multinic'
BASE_POLICY_NAME = 'os_compute_api:os-multinic:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    ROOT_POLICY,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""


multinic_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'add',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Add a fixed IP address to a server.

This API is proxy calls to the Network service. This is
deprecated.""",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (addFixedIp)'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'remove',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Remove a fixed IP address from a server.

This API is proxy calls to the Network service. This is
deprecated.""",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (removeFixedIp)'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
]


def list_rules():
    return multinic_policies
