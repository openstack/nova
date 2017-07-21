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


POLICY_ROOT = 'os_compute_api:os-quota-sets:%s'


quota_sets_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update',
        base.RULE_ADMIN_API,
        "Update the quotas",
        [
            {
                'method': 'PUT',
                'path': '/os-quota-sets/{tenant_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'defaults',
        base.RULE_ANY,
        "List default quotas",
        [
            {
                'method': 'GET',
                'path': '/os-quota-sets/{tenant_id}/defaults'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        base.RULE_ADMIN_OR_OWNER,
        "Show a quota",
        [
            {
                'method': 'GET',
                'path': '/os-quota-sets/{tenant_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_API,
        "Revert quotas to defaults",
        [
            {
                'method': 'DELETE',
                'path': '/os-quota-sets/{tenant_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'detail',
        base.RULE_ADMIN_OR_OWNER,
        "Show the detail of quota",
        [
            {
                'method': 'GET',
                'path': '/os-quota-sets/{tenant_id}/detail'
            }
        ]),
]


def list_rules():
    return quota_sets_policies
