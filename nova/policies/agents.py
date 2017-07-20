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


BASE_POLICY_NAME = 'os_compute_api:os-agents'


agents_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """Create, list, update, and delete guest agent builds

This is XenAPI driver specific.
It is used to force the upgrade of the XenAPI guest agent on instance boot.
""",
        [
            {
                'path': '/os-agents',
                'method': 'GET'
            },
            {
                'path': '/os-agents',
                'method': 'POST'
            },
            {
                'path': '/os-agents/{agent_build_id}',
                'method': 'PUT'
            },
            {
                'path': '/os-agents/{agent_build_id}',
                'method': 'DELETE'
            }
        ]),
]


def list_rules():
    return agents_policies
