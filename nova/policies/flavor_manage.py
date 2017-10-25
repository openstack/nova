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


BASE_POLICY_NAME = 'os_compute_api:os-flavor-manage'
POLICY_ROOT = 'os_compute_api:os-flavor-manage:%s'
BASE_POLICY_RULE = 'rule:%s' % BASE_POLICY_NAME


flavor_manage_policies = [
    # TODO(rb560u): remove this rule in future release
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        "Create and delete Flavors. Deprecated in Pike and will be "
        "removed in future release",
        [
            {
                'method': 'POST',
                'path': '/flavors'
            },
            {
                'method': 'DELETE',
                'path': '/flavors/{flavor_id}'
            },

        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        BASE_POLICY_RULE,
        "Create a flavor",
        [
            {
                'method': 'POST',
                'path': '/flavors'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'update',
        base.RULE_ADMIN_API,
        "Update a flavor",
        [
            {
                'method': 'PUT',
                'path': '/flavors/{flavor_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        BASE_POLICY_RULE,
        "Delete a flavor",
        [
            {
                'method': 'DELETE',
                'path': '/flavors/{flavor_id}'
            }
        ]),
]


def list_rules():
    return flavor_manage_policies
