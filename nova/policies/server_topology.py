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


BASE_POLICY_NAME = 'compute:server:topology:%s'

server_topology_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME % 'index',
        base.RULE_ADMIN_OR_OWNER,
        "Show the NUMA topology data for a server",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/topology'
            }
        ]),
    policy.DocumentedRuleDefault(
        # Control host NUMA node and cpu pinning information
        BASE_POLICY_NAME % 'host:index',
        base.RULE_ADMIN_API,
        "Show the NUMA topology data for a server with host NUMA ID and CPU "
        "pinning information",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/topology'
            }
        ]),
]


def list_rules():
    return server_topology_policies
