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


BASE_POLICY_NAME = 'os_compute_api:os-attach-interfaces'
POLICY_ROOT = 'os_compute_api:os-attach-interfaces:%s'


attach_interfaces_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="List port interfaces or show details of a port interface "
        "attached to a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-interface'
            },
            {
                'method': 'GET',
                'path': '/servers/{server_id}/os-interface/{port_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Attach an interface to a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/os-interface'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Detach an interface from a server",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/os-interface/{port_id}'
            }
        ],
        scope_types=['system', 'project'])
]


def list_rules():
    return attach_interfaces_policies
