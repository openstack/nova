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


BASE_POLICY_NAME = 'os_compute_api:os-used-limits'


used_limits_policies = [
    # TODO(aunnam): Remove this rule after we separate the scope check from
    # policies, as this is only checking the scope.
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """Show rate and absolute limits for the project.

This policy only checks if the user has access to the requested
project limits. And this check is performed only after the check
os_compute_api:limits passes""",
        [
            {
                'method': 'GET',
                'path': '/limits'
            }
        ]),
]


def list_rules():
    return used_limits_policies
