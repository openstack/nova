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


POLICY_ROOT = 'os_compute_api:os-keypairs:%s'


keypairs_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'index',
        'rule:admin_api or user_id:%(user_id)s',
        "List all keypairs",
        [
            {
                'path': '/os-keypairs',
                'method': 'GET'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        'rule:admin_api or user_id:%(user_id)s',
        "Create a keypair",
        [
            {
                'path': '/os-keypairs',
                'method': 'POST'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        'rule:admin_api or user_id:%(user_id)s',
        "Delete a keypair",
        [
            {
                'path': '/os-keypairs/{keypair_name}',
                'method': 'DELETE'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        'rule:admin_api or user_id:%(user_id)s',
        "Show details of a keypair",
        [
            {
                'path': '/os-keypairs/{keypair_name}',
                'method': 'GET'
            }
        ]),
]


def list_rules():
    return keypairs_policies
