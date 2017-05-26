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


BASE_POLICY_NAME = 'os_compute_api:flavors'


flavors_policies = [
    # TODO(johngarbutt) this doesn't appear to be used in the code and
    # as such should be removed.
    policy.RuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description='Deprecated in Pike and will be removed in next release'),
]


def list_rules():
    return flavors_policies
