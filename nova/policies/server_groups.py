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


BASE_POLICY_NAME = 'os_compute_api:os-server-groups'
POLICY_ROOT = 'os_compute_api:os-server-groups:%s'
BASE_POLICY_RULE = 'rule:%s' % BASE_POLICY_NAME


server_groups_policies = [
    # TODO(Kevin_Zheng): remove this rule as this not used by any API
    policy.RuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description='Deprecated in Pike and will be removed in next release'),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        BASE_POLICY_RULE,
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
        BASE_POLICY_RULE,
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
        BASE_POLICY_RULE,
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
        BASE_POLICY_RULE,
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
