# Copyright 2023 SAP SE
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


POLICY_ROOT = 'os_compute_api:sap:%s'


sap_admin_api_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'endpoints:list',
        check_str=base.RULE_ADMIN_API,
        description="List SAP admin API endpoints",
        operations=[
            {
                'method': 'GET',
                'path': '/sap/endpoints'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'clear-quota-resources-cache',
        check_str=base.RULE_ADMIN_API,
        description="Clear the cache of known resources in the quota engine",
        operations=[
            {
                'method': 'POST',
                'path': '/sap/clear_quota_resources_cache'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'in-cluster-vmotion',
        check_str=base.RULE_ADMIN_API,
        description="vMotion a VM inside its cluster",
        operations=[
            {
                'method': 'POST',
                'path': '/sap/in_cluster_vmotion'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'usage-by-az',
        check_str=base.RULE_ADMIN_API,
        description="Show project usages split by availability-zone",
        operations=[
            {
                'method': 'GET',
                'path': '/sap/usage_by_az'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'get-scheduler-settings',
        check_str=base.RULE_ADMIN_API,
        description="Expose the current scheduler settings",
        operations=[
            {
                'method': 'GET',
                'path': '/sap/get_scheduler_settings'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return sap_admin_api_policies
