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
        name=POLICY_ROOT % 'add_tenant_access',
        check_str=base.RULE_ADMIN_API,
        description="Add flavor access to a tenant",
        operations=[
            {
                'method': 'POST',
                'path': '/flavors/{flavor_id}/action (addTenantAccess)'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'remove_tenant_access',
        check_str=base.RULE_ADMIN_API,
        description="Remove flavor access from a tenant",
        operations=[
            {
                'method': 'POST',
                'path': '/flavors/{flavor_id}/action (removeTenantAccess)'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="""List flavor access information

Allows access to the full list of tenants that have access
to a flavor via an os-flavor-access API.
""",
        operations=[
            {
                'method': 'GET',
                'path': '/flavors/{flavor_id}/os-flavor-access'
            },
        ],
        # NOTE(gmann): This policy is admin_or_owner by default but allowed
        # for everyone, bug#1867840. There can be multiple project with access
        # to specific flavorso we cannot say there is single owner of flavor.
        # Only admin should be able to list the projects having access to any
        # flavor. We should change this policy defaults to admin only. I am
        # seeting scope as 'system' only and new defaults can be SYSTEM_ADMIN.
        scope_types=['system']),
]


def list_rules():
    return flavor_access_policies
