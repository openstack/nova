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


BASE_POLICY_NAME = 'os_compute_api:os-instance-usage-audit-log'


instance_usage_audit_log_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        "List all usage audits and that occurred before a specified time "
        "for all servers on all compute hosts where usage auditing is "
        "configured",
        [
            {
                'method': 'GET',
                'path': '/os-instance_usage_audit_log'
            },
            {
                'method': 'GET',
                'path': '/os-instance_usage_audit_log/{before_timestamp}'
            }
        ]),
]


def list_rules():
    return instance_usage_audit_log_policies
