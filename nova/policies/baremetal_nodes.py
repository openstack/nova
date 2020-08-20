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


ROOT_POLICY = 'os_compute_api:os-baremetal-nodes'
BASE_POLICY_NAME = 'os_compute_api:os-baremetal-nodes:%s'

DEPRECATED_BAREMETAL_POLICY = policy.DeprecatedRule(
    ROOT_POLICY,
    base.RULE_ADMIN_API,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""


baremetal_nodes_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'list',
        check_str=base.SYSTEM_READER,
        description="""List and show details of bare metal nodes.

These APIs are proxy calls to the Ironic service and are deprecated.
""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-baremetal-nodes'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_BAREMETAL_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'show',
        check_str=base.SYSTEM_READER,
        description="""Show action details for a server.""",
        operations=[
            {
                'method': 'GET',
                'path': '/os-baremetal-nodes/{node_id}'
            }
        ],
        scope_types=['system'],
        deprecated_rule=DEPRECATED_BAREMETAL_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0')
]


def list_rules():
    return baremetal_nodes_policies
