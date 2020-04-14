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


ROOT_POLICY = 'os_compute_api:os-instance-actions'
BASE_POLICY_NAME = 'os_compute_api:os-instance-actions:%s'

DEPRECATED_INSTANCE_ACTION_POLICY = policy.DeprecatedRule(
    ROOT_POLICY,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

instance_actions_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'events:details',
        check_str=base.SYSTEM_READER,
        description="""Add "details" key in action events for a server.

This check is performed only after the check
os_compute_api:os-instance-actions:show passes. Beginning with Microversion
2.84, new field 'details' is exposed via API which can have more details about
event failure. That field is controlled by this policy which is system reader
by default. Making the 'details' field visible to the non-admin user helps to
understand the nature of the problem (i.e. if the action can be retried),
but in the other hand it might leak information about the deployment
(e.g. the type of the hypervisor).
""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions/{request_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'events',
        check_str=base.SYSTEM_READER,
        description="""Add events details in action details for a server.
This check is performed only after the check
os_compute_api:os-instance-actions:show passes. Beginning with Microversion
2.51, events details are always included; traceback information is provided
per event if policy enforcement passes. Beginning with Microversion 2.62,
each event includes a hashed host identifier and, if policy enforcement
passes, the name of the host.""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions/{request_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""List actions for a server.""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INSTANCE_ACTION_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""Show action details for a server.""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-instance-actions/{request_id}'
            }
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_INSTANCE_ACTION_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
]


def list_rules():
    return instance_actions_policies
