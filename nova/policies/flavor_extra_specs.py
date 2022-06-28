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

POLICY_ROOT = 'os_compute_api:os-flavor-extra-specs:%s'

flavor_extra_specs_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.PROJECT_READER_OR_ADMIN,
        description="Show an extra spec for a flavor",
        operations=[
            {
                'path': '/flavors/{flavor_id}/os-extra_specs/'
                        '{flavor_extra_spec_key}',
                'method': 'GET'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.ADMIN,
        description="Create extra specs for a flavor",
        operations=[
            {
                'path': '/flavors/{flavor_id}/os-extra_specs/',
                'method': 'POST'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.ADMIN,
        description="Update an extra spec for a flavor",
        operations=[
            {
                'path': '/flavors/{flavor_id}/os-extra_specs/'
                        '{flavor_extra_spec_key}',
                'method': 'PUT'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.ADMIN,
        description="Delete an extra spec for a flavor",
        operations=[
            {
                'path': '/flavors/{flavor_id}/os-extra_specs/'
                        '{flavor_extra_spec_key}',
                'method': 'DELETE'
            }
        ],
        scope_types=['project']
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_READER_OR_ADMIN,
        description="List extra specs for a flavor. Starting with "
        "microversion 2.61, extra specs may be returned in responses "
        "for the flavor resource.",
        operations=[
            {
                'path': '/flavors/{flavor_id}/os-extra_specs/',
                'method': 'GET'
            },
            # Microversion 2.61 operations for flavors:
            {
                'path': '/flavors',
                'method': 'POST'
            },
            {
                'path': '/flavors/detail',
                'method': 'GET'
            },
            {
                'path': '/flavors/{flavor_id}',
                'method': 'GET'
            },
            {
                'path': '/flavors/{flavor_id}',
                'method': 'PUT'
            }
        ],
        scope_types=['project']
    ),
]


def list_rules():
    return flavor_extra_specs_policies
