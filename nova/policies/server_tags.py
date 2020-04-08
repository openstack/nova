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


POLICY_ROOT = 'os_compute_api:os-server-tags:%s'


server_tags_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete_all',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Delete all the server tags",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/tags'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List all tags for given server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/tags'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update_all',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Replace all tags on specified server with the new set "
        "of tags.",
        operations=[
            {
                'method': 'PUT',
                'path': '/servers/{server_id}/tags'

            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Delete a single tag from the specified server",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/tags/{tag}'
            }
        ],
        scope_types=['system', 'project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Add a single tag to the server if server has no "
        "specified tag",
        operations=[
            {
                'method': 'PUT',
                'path': '/servers/{server_id}/tags/{tag}'
            }
        ],
        scope_types=['system', 'project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="Check tag existence on the server.",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/tags/{tag}'
            }
        ],
        scope_types=['system', 'project']
    ),
]


def list_rules():
    return server_tags_policies
