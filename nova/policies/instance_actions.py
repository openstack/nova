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


BASE_POLICY_NAME = 'os_compute_api:os-instance-actions'
POLICY_ROOT = 'os_compute_api:os-instance-actions:%s'


instance_actions_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'events',
        base.RULE_ADMIN_API,
        """Add events details in action details for a server.

This check is performed only after the check
os_compute_api:os-instance-actions passes. Beginning with
Microversion 2.51, events details are always included; traceback
information is provided per event if policy enforcement passes.
Beginning with Microversion 2.62, each event includes a hashed
host identifier and, if policy enforcement passes, the name of
the host.""",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions/{request_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        """List actions and show action details for a server.""",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions'
            },
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions/{request_id}'
            }
        ]),
]


def list_rules():
    return instance_actions_policies
