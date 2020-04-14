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

POLICY_ROOT = 'os_compute_api:os-keypairs:%s'


keypairs_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str='(' + base.SYSTEM_READER + ') or user_id:%(user_id)s',
        description="List all keypairs",
        operations=[
            {
                'path': '/os-keypairs',
                'method': 'GET'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str='(' + base.SYSTEM_ADMIN + ') or user_id:%(user_id)s',
        description="Create a keypair",
        operations=[
            {
                'path': '/os-keypairs',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str='(' + base.SYSTEM_ADMIN + ') or user_id:%(user_id)s',
        description="Delete a keypair",
        operations=[
            {
                'path': '/os-keypairs/{keypair_name}',
                'method': 'DELETE'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str='(' + base.SYSTEM_READER + ') or user_id:%(user_id)s',
        description="Show details of a keypair",
        operations=[
            {
                'path': '/os-keypairs/{keypair_name}',
                'method': 'GET'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return keypairs_policies
