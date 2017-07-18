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


POLICY_ROOT = 'os_compute_api:os-availability-zone:%s'


availability_zone_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'list',
        base.RULE_ADMIN_OR_OWNER,
        "List availability zone information without host information",
        [
            {
                'method': 'GET',
                'path': 'os-availability-zone'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'detail',
        base.RULE_ADMIN_API,
        "List detailed availability zone information with host information",
        [
            {
                'method': 'GET',
                'path': '/os-availability-zone/detail'
            }
        ])
]


def list_rules():
    return availability_zone_policies
