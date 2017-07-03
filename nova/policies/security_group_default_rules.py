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


BASE_POLICY_NAME = 'os_compute_api:os-security-group-default-rules'


security_group_default_rules_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """List, show information for, create, or delete default security
group rules.

These APIs are only available with nova-network which is now deprecated.""",
        [
            {
                'method': 'GET',
                'path': '/os-security-group-default-rules'
            },
            {
                'method': 'GET',
                'path': '/os-security-group-default-rules'
                        '/{security_group_default_rule_id}'
            },
            {
                'method': 'POST',
                'path': '/os-security-group-default-rules'
            },
            {
                'method': 'DELETE',
                'path': '/os-security-group-default-rules'
                        '/{security_group_default_rule_id}'
            }
        ]),
]


def list_rules():
    return security_group_default_rules_policies
