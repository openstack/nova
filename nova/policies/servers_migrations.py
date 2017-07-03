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
        POLICY_ROOT % 'show',
        base.RULE_ADMIN_API,
        "Show details for an in-progress live migration for a given server",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'force_complete',
        base.RULE_ADMIN_API,
        "Force an in-progress live migration for a given server to complete",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/migrations/{migration_id}'
                        '/action (force_complete)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_API,
        "Delete(Abort) an in-progress live migration",
        [
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/migrations/{migration_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'index',
        base.RULE_ADMIN_API,
        "Lists in-progress live migrations for a given server",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/migrations'
            }
        ]),
]


def list_rules():
    return servers_migrations_policies
