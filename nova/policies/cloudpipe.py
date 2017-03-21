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


BASE_POLICY_NAME = 'os_compute_api:os-cloudpipe'
POLICY_ROOT = 'os_compute_api:os-cloudpipe:%s'


cloudpipe_policies = [
    base.create_rule_default(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """List, create and update cloud pipes.

os-cloudpipe API is deprecated as this works only with nova-network which \
itself is deprecated.
""",
        [
            {
                'method': 'GET',
                'path': '/os-cloudpipe'
            },
            {
                'method': 'POST',
                'path': '/os-cloudpipe'
            },
            {
                'method': 'PUT',
                'path': '/os-cloudpipe/configure-project'
            }
        ]),
    policy.RuleDefault(
        name=POLICY_ROOT % 'discoverable',
        check_str=base.RULE_ANY),
]


def list_rules():
    return cloudpipe_policies
