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


BASE_POLICY_NAME = 'os_compute_api:os-services'


services_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_API,
        "List all running Compute services in a region, enables or disable "
        "scheduling for a Compute service, logs disabled Compute service "
        "information, set or unset forced_down flag for the compute service "
        "and delete a Compute service",
        [
            {
                'method': 'GET',
                'path': '/os-services'
            },
            {
                'method': 'PUT',
                'path': '/os-services/enable'
            },
            {
                'method': 'PUT',
                'path': '/os-services/disable'
            },
            {
                'method': 'PUT',
                'path': '/os-services/disable-log-reason'
            },
            {
                'method': 'PUT',
                'path': '/os-services/force-down'
            },
            {
                # Added in microversion 2.53.
                'method': 'PUT',
                'path': '/os-services/{service_id}'
            },
            {
                'method': 'DELETE',
                'path': '/os-services/{service_id}'
            }
        ]),
]


def list_rules():
    return services_policies
