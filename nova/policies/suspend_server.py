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


POLICY_ROOT = 'os_compute_api:os-suspend-server:%s'


suspend_server_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'resume',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Resume suspended server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resume)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'suspend',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Suspend server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (suspend)'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return suspend_server_policies
