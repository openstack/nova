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


POLICY_ROOT = 'os_compute_api:os-shelve:%s'


shelve_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'shelve',
        base.RULE_ADMIN_OR_OWNER,
        "Shelve server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (shelve)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'unshelve',
        base.RULE_ADMIN_OR_OWNER,
        "Unshelve (restore) shelved server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (unshelve)'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'shelve_offload',
        base.RULE_ADMIN_API,
        "Shelf-offload (remove) server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (shelveOffload)'
            }
        ]),
]


def list_rules():
    return shelve_policies
