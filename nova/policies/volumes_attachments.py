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


POLICY_ROOT = 'os_compute_api:os-volumes-attachments:%s'


volumes_attachments_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List volume attachments for an instance",
        operations=[
            {'method': 'GET',
             'path': '/servers/{server_id}/os-volume_attachments'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Attach a volume to an instance",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/os-volume_attachments'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="Show details of a volume attachment",
        operations=[
            {
                'method': 'GET',
                'path':
                 '/servers/{server_id}/os-volume_attachments/{volume_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Update a volume attachment.
New 'update' policy about 'swap + update' request (which is possible
only >2.85) only <swap policy> is checked. We expect <swap policy> to be
always superset of this policy permission.
""",
        operations=[
            {
                'method': 'PUT',
                'path':
                 '/servers/{server_id}/os-volume_attachments/{volume_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'swap',
        check_str=base.SYSTEM_ADMIN,
        description="Update a volume attachment with a different volumeId",
        operations=[
            {
                'method': 'PUT',
                'path':
                 '/servers/{server_id}/os-volume_attachments/{volume_id}'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Detach a volume from an instance",
        operations=[
            {
                'method': 'DELETE',
                'path':
                 '/servers/{server_id}/os-volume_attachments/{volume_id}'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return volumes_attachments_policies
