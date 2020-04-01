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

# NOTE(gmann): Deprecating this policy explicitly as old defaults
# admin or owner is not suitable for that which should be admin (Bug#1867840)
# but changing that will break old deployment so let's keep supporting
# the old default also and new default can be SYSTEM_READER
# SYSTEM_READER rule in base class is defined with the deprecated rule of admin
# not admin or owner which is the main reason that we need to explicitly
# deprecate this policy here.
DEPRECATED_FLAVOR_ACCESS_POLICY = policy.DeprecatedRule(
    BASE_POLICY_NAME,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

flavor_access_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'add_tenant_access',
        check_str=base.SYSTEM_ADMIN,
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
        check_str=base.SYSTEM_ADMIN,
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
        check_str=base.SYSTEM_READER,
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
        scope_types=['system'],
        deprecated_rule=DEPRECATED_FLAVOR_ACCESS_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return flavor_access_policies
