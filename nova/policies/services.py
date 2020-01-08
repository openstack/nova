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


BASE_POLICY_NAME = 'os_compute_api:os-services:%s'
DEPRECATED_SERVICE_POLICY = policy.DeprecatedRule(
    'os_compute_api:os-services',
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

services_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.SYSTEM_READER,
        description="List all running Compute services in a region.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-services'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_SERVICE_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'update',
        check_str=base.SYSTEM_ADMIN,
        description="Update a Compute service.",
        operations=[
            {
                # Added in microversion 2.53.
                'method': 'PUT',
                'path': '/os-services/{service_id}'
            },
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_SERVICE_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'delete',
        check_str=base.SYSTEM_ADMIN,
        description="Delete a Compute service.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/os-services/{service_id}'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_SERVICE_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return services_policies
