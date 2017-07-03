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


BASE_POLICY_NAME = 'os_compute_api:os-hosts'


hosts_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """List, show and manage physical hosts.

These APIs are all deprecated in favor of os-hypervisors and os-services.""",
        [
            {
                'method': 'GET',
                'path': '/os-hosts'
            },
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}'
            },
            {
                'method': 'PUT',
                'path': '/os-hosts/{host_name}'
            },
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/reboot'
            },
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/shutdown'
            },
            {
                'method': 'GET',
                'path': '/os-hosts/{host_name}/startup'
            }
        ]),
]


def list_rules():
    return hosts_policies
