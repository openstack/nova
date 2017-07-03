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


BASE_POLICY_NAME = 'os_compute_api:os-networks'
POLICY_ROOT = 'os_compute_api:os-networks:%s'


networks_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """Create and delete a network, add and disassociate a network
from a project.

These APIs are only available with nova-network which is deprecated.""",
        [
            {
                'method': 'POST',
                'path': '/os-networks'
            },
            {
                'method': 'POST',
                'path': '/os-networks/add'
            },
            {
                'method': 'DELETE',
                'path': '/os-networks/{network_id}'
            },
            {
                'method': 'POST',
                'path': '/os-networks/{network_id}/action (disassociate)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'view',
        base.RULE_ADMIN_OR_OWNER,
        """List networks for the project and show details for a network.

These APIs are proxy calls to the Network service. These are all
deprecated.""",
        [
            {
                'method': 'GET',
                'path': '/os-networks'
            },
            {
                'method': 'GET',
                'path': '/os-networks/{network_id}'
            }
        ]),
]


def list_rules():
    return networks_policies
