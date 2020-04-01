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


POLICY_ROOT = 'os_compute_api:os-lock-server:%s'


lock_server_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'lock',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Lock a server",
        operations=[
            {
                'path': '/servers/{server_id}/action (lock)',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'unlock',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Unlock a server",
        operations=[
            {
                'path': '/servers/{server_id}/action (unlock)',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'unlock:unlock_override',
        check_str=base.SYSTEM_ADMIN,
        description="""Unlock a server, regardless who locked the server.

This check is performed only after the check
os_compute_api:os-lock-server:unlock passes""",
        operations=[
            {
                'path': '/servers/{server_id}/action (unlock)',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project']
    ),
]


def list_rules():
    return lock_server_policies
