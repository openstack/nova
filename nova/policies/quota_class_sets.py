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


POLICY_ROOT = 'os_compute_api:os-quota-class-sets:%s'


quota_class_sets_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        'is_admin:True or quota_class:%(quota_class)s',
        "List quotas for specific quota classs",
        [
            {
                'method': 'GET',
                'path': '/os-quota-class-sets/{quota_class}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update',
        base.RULE_ADMIN_API,
        'Update quotas for specific quota class',
        [
            {
                'method': 'PUT',
                'path': '/os-quota-class-sets/{quota_class}'
            }
        ]),
]


def list_rules():
    return quota_class_sets_policies
