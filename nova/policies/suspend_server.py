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
        POLICY_ROOT % 'resume',
        base.RULE_ADMIN_OR_OWNER,
        "Resume suspended server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resume)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'suspend',
        base.RULE_ADMIN_OR_OWNER,
        "Suspend server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (suspend)'
            }
        ]),
]


def list_rules():
    return suspend_server_policies
