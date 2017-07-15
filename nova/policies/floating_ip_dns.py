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


BASE_POLICY_NAME = 'os_compute_api:os-floating-ip-dns'
POLICY_ROOT = 'os_compute_api:os-floating-ip-dns:%s'


floating_ip_dns_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        """List registered DNS domains, and CRUD actions on domain names.

Note this only works with nova-network and this API is deprecated.""",
        [
            {
                'method': 'GET',
                'path': '/os-floating-ip-dns'
            },
            {
                'method': 'GET',
                'path': '/os-floating-ip-dns/{domain}/entries/{ip}'
            },
            {
                'method': 'GET',
                'path': '/os-floating-ip-dns/{domain}/entries/{name}'
            },
            {
                'method': 'PUT',
                'path': '/os-floating-ip-dns/{domain}/entries/{name}'
            },
            {
                'method': 'DELETE',
                'path': '/os-floating-ip-dns/{domain}/entries/{name}'
            },
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'domain:update',
        base.RULE_ADMIN_API,
        "Create or update a DNS domain.",
        [
            {
                'method': 'PUT',
                'path': '/os-floating-ip-dns/{domain}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'domain:delete',
        base.RULE_ADMIN_API,
        "Delete a DNS domain.",
        [
            {
                'method': 'DELETE',
                'path': '/os-floating-ip-dns/{domain}'
            }
        ]),
]


def list_rules():
    return floating_ip_dns_policies
