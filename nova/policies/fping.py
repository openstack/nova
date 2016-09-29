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


BASE_POLICY_NAME = 'os_compute_api:os-fping'
POLICY_ROOT = 'os_compute_api:os-fping:%s'


fping_policies = [
    policy.RuleDefault(
        name=POLICY_ROOT % 'all_tenants',
        check_str=base.RULE_ADMIN_API),
    policy.RuleDefault(
        name=POLICY_ROOT % 'discoverable',
        check_str=base.RULE_ANY),
    policy.RuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER),
]


def list_rules():
    return fping_policies
