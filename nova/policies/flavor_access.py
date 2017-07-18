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


BASE_POLICY_NAME = 'os_compute_api:os-flavor-access'
POLICY_ROOT = 'os_compute_api:os-flavor-access:%s'


flavor_access_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'add_tenant_access',
        base.RULE_ADMIN_API,
        "Add flavor access to a tenant",
        [
            {
                'method': 'POST',
                'path': '/flavors/{flavor_id}/action (addTenantAccess)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'remove_tenant_access',
        base.RULE_ADMIN_API,
        "Remove flavor access from a tenant",
        [
            {
                'method': 'POST',
                'path': '/flavors/{flavor_id}/action (removeTenantAccess)'
            }
        ]),
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        """List flavor access information

Adds the os-flavor-access:is_public key into several flavor APIs.

It also allows access to the full list of tenants that have access
to a flavor via an os-flavor-access API.
""",
        [
            {
                'method': 'GET',
                'path': '/flavors/{flavor_id}/os-flavor-access'
            },
            {
                'method': 'GET',
                'path': '/flavors/detail'
            },
            {
                'method': 'GET',
                'path': '/flavors/{flavor_id}'
            },
            {
                'method': 'POST',
                'path': '/flavors'
            },
        ]),
]


def list_rules():
    return flavor_access_policies
