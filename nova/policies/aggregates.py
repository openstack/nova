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


POLICY_ROOT = 'os_compute_api:os-aggregates:%s'
NEW_POLICY_ROOT = 'compute:aggregates:%s'


aggregates_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'set_metadata',
        check_str=base.SYSTEM_ADMIN,
        description="Create or replace metadata for an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}/action (set_metadata)',
                'method': 'POST'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'add_host',
        check_str=base.SYSTEM_ADMIN,
        description="Add a host to an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}/action (add_host)',
                'method': 'POST'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.SYSTEM_ADMIN,
        description="Create an aggregate",
        operations=[
            {
                'path': '/os-aggregates',
                'method': 'POST'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'remove_host',
        check_str=base.SYSTEM_ADMIN,
        description="Remove a host from an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}/action (remove_host)',
                'method': 'POST'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.SYSTEM_ADMIN,
        description="Update name and/or availability zone for an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}',
                'method': 'PUT'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_READER,
        description="List all aggregates",
        operations=[
            {
                'path': '/os-aggregates',
                'method': 'GET'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.SYSTEM_ADMIN,
        description="Delete an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}',
                'method': 'DELETE'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_READER,
        description="Show details for an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}',
                'method': 'GET'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=NEW_POLICY_ROOT % 'images',
        check_str=base.SYSTEM_ADMIN,
        description="Request image caching for an aggregate",
        operations=[
            {
                'path': '/os-aggregates/{aggregate_id}/images',
                'method': 'POST'
            }
        ],
        scope_types=['system']),
]


def list_rules():
    return aggregates_policies
