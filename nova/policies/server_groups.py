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


POLICY_ROOT = 'os_compute_api:os-server-groups:%s'


server_groups_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        base.RULE_ADMIN_OR_OWNER,
        "Create a new server group",
        [
            {
                'path': '/os-server-groups',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_OR_OWNER,
        "Delete a server group",
        [
            {
                'path': '/os-server-groups/{server_group_id}',
                'method': 'DELETE'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'index',
        base.RULE_ADMIN_OR_OWNER,
        "List all server groups",
        [
            {
                'path': '/os-server-groups',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        base.RULE_ADMIN_OR_OWNER,
        "Show details of a server group",
        [
            {
                'path': '/os-server-groups/{server_group_id}',
                'method': 'GET'
            }
        ]
    ),
]


def list_rules():
    return server_groups_policies
