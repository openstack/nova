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


BASE_POLICY_NAME = 'os_compute_api:os-admin-password'


admin_password_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Change the administrative password for a server",
        operations=[
            {
                'path': '/servers/{server_id}/action (changePassword)',
                'method': 'POST'
            }
        ],
        scope_types=['system', 'project'])
]


def list_rules():
    return admin_password_policies
