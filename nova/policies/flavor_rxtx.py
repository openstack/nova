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


BASE_POLICY_NAME = 'os_compute_api:os-flavor-rxtx'


flavor_rxtx_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        "Add the rxtx_factor key into some Flavor APIs",
        [
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
    return flavor_rxtx_policies
