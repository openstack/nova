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


POLICY_ROOT = 'os_compute_api:server-metadata:%s'


server_metadata_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'index',
        base.RULE_ADMIN_OR_OWNER,
        "List all metadata of a server",
        [
            {
                'path': '/servers/{server_id}/metadata',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        base.RULE_ADMIN_OR_OWNER,
        "Show metadata for a server",
        [
            {
                'path': '/servers/{server_id}/metadata/{key}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        base.RULE_ADMIN_OR_OWNER,
        "Create metadata for a server",
        [
            {
                'path': '/servers/{server_id}/metadata',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update_all',
        base.RULE_ADMIN_OR_OWNER,
        "Replace metadata for a server",
        [
            {
                'path': '/servers/{server_id}/metadata',
                'method': 'PUT'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update',
        base.RULE_ADMIN_OR_OWNER,
        "Update metadata from a server",
        [
            {
                'path': '/servers/{server_id}/metadata/{key}',
                'method': 'PUT'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_OR_OWNER,
        "Delete metadata from a server",
        [
            {
                'path': '/servers/{server_id}/metadata/{key}',
                'method': 'DELETE'
            }
        ]
    ),
]


def list_rules():
    return server_metadata_policies
