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


POLICY_ROOT = 'os_compute_api:os-assisted-volume-snapshots:%s'


assisted_volume_snapshots_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        # TODO(gmann): This is internal API policy and called by
        # cinder. Add 'service' role in this policy so that cinder
        # can call it with user having 'service' role (not having
        # correct project_id). That is for phase-2 of RBAC goal and until
        # then, we keep it open for all admin in any project. We cannot
        # default it to PROJECT_ADMIN which has the project_id in
        # check_str and will fail if cinder call it with other project_id.
        check_str=base.ADMIN,
        description="Create an assisted volume snapshot",
        operations=[
            {
                'path': '/os-assisted-volume-snapshots',
                'method': 'POST'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        # TODO(gmann): This is internal API policy and called by
        # cinder. Add 'service' role in this policy so that cinder
        # can call it with user having 'service' role (not having
        # correct project_id). That is for phase-2 of RBAC goal and until
        # then, we keep it open for all admin in any project. We cannot
        # default it to PROJECT_ADMIN which has the project_id in
        # check_str and will fail if cinder call it with other project_id.
        check_str=base.ADMIN,
        description="Delete an assisted volume snapshot",
        operations=[
            {
                'path': '/os-assisted-volume-snapshots/{snapshot_id}',
                'method': 'DELETE'
            }
        ],
        scope_types=['project']),
]


def list_rules():
    return assisted_volume_snapshots_policies
