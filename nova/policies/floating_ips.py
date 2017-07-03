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


BASE_POLICY_NAME = 'os_compute_api:os-floating-ips'


floating_ips_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        "Manage a project's floating IPs. These APIs are all deprecated.",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (addFloatingIp)'
            },
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (removeFloatingIp)'
            },
            {
                'method': 'GET',
                'path': '/os-floating-ips'
            },
            {
                'method': 'POST',
                'path': '/os-floating-ips'
            },
            {
                'method': 'GET',
                'path': '/os-floating-ips/{floating_ip_id}'
            },
            {
                'method': 'DELETE',
                'path': '/os-floating-ips/{floating_ip_id}'
            },
        ]),
]


def list_rules():
    return floating_ips_policies
