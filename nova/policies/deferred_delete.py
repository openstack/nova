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


BASE_POLICY_NAME = 'os_compute_api:os-deferred-delete:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-deferred-delete',
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

deferred_delete_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'restore',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Restore a soft deleted server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (restore)'
            },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'force',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Force delete a server before deferred cleanup",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (forceDelete)'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0')
]


def list_rules():
    return deferred_delete_policies
