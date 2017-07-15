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


POLICY_ROOT = 'os_compute_api:os-admin-actions:%s'


admin_actions_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'reset_state',
        base.RULE_ADMIN_API,
        "Reset the state of a given server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-resetState)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'inject_network_info',
        base.RULE_ADMIN_API,
        "Inject network information into the server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (injectNetworkInfo)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'reset_network',
        base.RULE_ADMIN_API,
        "Reset networking on a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resetNetwork)'
            }
        ])
]


def list_rules():
    return admin_actions_policies
