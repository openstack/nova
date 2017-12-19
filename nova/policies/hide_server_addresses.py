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

BASE_POLICY_NAME = 'os_compute_api:os-hide-server-addresses'


hide_server_addresses_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        'is_admin:False',
        """Hide server's 'addresses' key in the server response.

This set the 'addresses' key in the server response to an empty
dictionary when the server is in a specific set of states as
defined in CONF.api.hide_server_address_states.
By default 'addresses' is hidden only when the server is in
'BUILDING' state.""",
        [
            {
                'method': 'GET',
                'path': '/servers/{id}'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ],
        deprecated_for_removal=True,
        deprecated_reason=(
            'Capability of configuring the server states to hide the '
            'address has been deprecated for removal. Now this policy is '
            'not needed to control the server address'
        ),
        deprecated_since='17.0.0'),
]


def list_rules():
    return hide_server_addresses_policies
