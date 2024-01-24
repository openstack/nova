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
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_READER,
        description="List quotas for specific quota classs",
        operations=[
            {
                'method': 'GET',
                'path': '/os-quota-class-sets/{quota_class}'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.SYSTEM_ADMIN,
        description='Update quotas for specific quota class',
        operations=[
            {
                'method': 'PUT',
                'path': '/os-quota-class-sets/{quota_class}'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.SYSTEM_ADMIN,
        description='Ensure quotas exist for a quota class',
        operations=[
            {
                'method': 'POST',
                'path': '/os-quota-class-sets/{quota_class}'
            }
        ],
        scope_types=['system']),
]


def list_rules():
    return quota_class_sets_policies
