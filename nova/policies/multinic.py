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


BASE_POLICY_NAME = 'os_compute_api:os-multinic'


multinic_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        """Add or remove a fixed IP address from a server.

These APIs are proxy calls to the Network service. These are all
deprecated.""",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (addFixedIp)'
            },
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (removeFixedIp)'
            }
        ]),
]


def list_rules():
    return multinic_policies
