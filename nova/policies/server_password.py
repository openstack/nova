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


BASE_POLICY_NAME = 'os_compute_api:os-server-password:%s'

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

DEPRECATED_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-server-password',
    base.RULE_ADMIN_OR_OWNER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='21.0.0'
)


server_password_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'show',
        check_str=base.PROJECT_READER_OR_ADMIN,
        description="Show the encrypted administrative "
        "password of a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-server-password'
            },
        ],
        scope_types=['project'],
        deprecated_rule=DEPRECATED_POLICY),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'clear',
        check_str=base.PROJECT_MEMBER_OR_ADMIN,
        description="Clear the encrypted administrative "
        "password of a server",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/os-server-password'
            }
        ],
        scope_types=['project'],
        deprecated_rule=DEPRECATED_POLICY),
]


def list_rules():
    return server_password_policies
