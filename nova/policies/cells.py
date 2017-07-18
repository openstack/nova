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


BASE_POLICY_NAME = 'os_compute_api:os-cells'
POLICY_ROOT = 'os_compute_api:os-cells:%s'


cells_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update',
        base.RULE_ADMIN_API,
        'Update an existing cell',
        [
            {
                'method': 'PUT',
                'path': '/os-cells/{cell_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        base.RULE_ADMIN_API,
        'Create a new cell',
        [
            {
                'method': 'POST',
                'path': '/os-cells'
            }
        ]),
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        'List and show detailed info for a given cell or all cells',
        [
            {
                'method': 'GET',
                'path': '/os-cells'
            },
            {
                'method': 'GET',
                'path': '/os-cells/detail'
            },
            {
                'method': 'GET',
                'path': '/os-cells/info'
            },
            {
                'method': 'GET',
                'path': '/os-cells/capacities'
            },
            {
                'method': 'GET',
                'path': '/os-cells/{cell_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'sync_instances',
        base.RULE_ADMIN_API,
        'Sync instances info in all cells',
        [
            {
                'method': 'POST',
                'path': '/os-cells/sync_instances'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_API,
        'Remove a cell',
        [
            {
                'method': 'DELETE',
                'path': '/os-cells/{cell_id}'
            }
        ])
]


def list_rules():
    return cells_policies
