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
        name=POLICY_ROOT % 'reset_state',
        check_str=base.SYSTEM_ADMIN,
        description="Reset the state of a given server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-resetState)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'inject_network_info',
        check_str=base.SYSTEM_ADMIN,
        description="Inject network information into the server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (injectNetworkInfo)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'reset_network',
        check_str=base.SYSTEM_ADMIN,
        description="Reset networking on a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resetNetwork)'
            }
        ],
        scope_types=['system', 'project'])
]


def list_rules():
    return admin_actions_policies
