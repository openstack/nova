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
        name=POLICY_ROOT % 'create',
        check_str=base.PROJECT_MEMBER_OR_ADMIN,
        description="Create a new server group",
        operations=[
            {
                'path': '/os-server-groups',
                'method': 'POST'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.PROJECT_MEMBER_OR_ADMIN,
        description="Delete a server group",
        operations=[
            {
                'path': '/os-server-groups/{server_group_id}',
                'method': 'DELETE'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_READER_OR_ADMIN,
        description="List all server groups",
        operations=[
            {
                'path': '/os-server-groups',
                'method': 'GET'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index:all_projects',
        check_str=base.ADMIN,
        description="List all server groups for all projects",
        operations=[
            {
                'path': '/os-server-groups',
                'method': 'GET'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.PROJECT_READER_OR_ADMIN,
        description="Show details of a server group",
        operations=[
            {
                'path': '/os-server-groups/{server_group_id}',
                'method': 'GET'
            }
        ],
        scope_types=['project']
    ),
]


def list_rules():
    return server_groups_policies
