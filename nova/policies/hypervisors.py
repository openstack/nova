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


BASE_POLICY_NAME = 'os_compute_api:os-hypervisors'


hypervisors_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        """Policy rule for hypervisor related APIs.

This rule will be checked for the following APIs:

List all hypervisors, list all hypervisors with details, show
summary statistics for all hypervisors over all compute nodes,
show details for a hypervisor, show the uptime of a hypervisor,
search hypervisor by hypervisor_hostname pattern and list all
servers on hypervisors that can match the provided
hypervisor_hostname pattern.""",
        [
            {
                'path': '/os-hypervisors',
                'method': 'GET'
            },
            {
                'path': '/os-hypervisors/details',
                'method': 'GET'
            },
            {
                'path': '/os-hypervisors/statistics',
                'method': 'GET'
            },
            {
                'path': '/os-hypervisors/{hypervisor_id}',
                'method': 'GET'
            },
            {
                'path': '/os-hypervisors/{hypervisor_id}/uptime',
                'method': 'GET'
            },
            {
                'path': '/os-hypervisors/{hypervisor_hostname_pattern}/search',
                'method': 'GET'
            },
            {
                'path':
                '/os-hypervisors/{hypervisor_hostname_pattern}/servers',
                'method': 'GET'
            }
        ]
    ),
]


def list_rules():
    return hypervisors_policies
