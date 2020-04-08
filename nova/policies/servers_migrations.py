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


POLICY_ROOT = 'os_compute_api:servers:migrations:%s'


servers_migrations_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_READER,
        description="Show details for an in-progress live migration for a "
        "given server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'force_complete',
        check_str=base.SYSTEM_ADMIN,
        description="Force an in-progress live migration for a given server "
        "to complete",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/migrations/{migration_id}'
                        '/action (force_complete)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.SYSTEM_ADMIN,
        description="Delete(Abort) an in-progress live migration",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_READER,
        description="Lists in-progress live migrations for a given server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return servers_migrations_policies
