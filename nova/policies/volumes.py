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


BASE_POLICY_NAME = 'os_compute_api:os-volumes'
POLICY_NAME = 'os_compute_api:os-volumes:%s'

DEPRECATED_POLICY = policy.DeprecatedRule(
    BASE_POLICY_NAME,
    base.RULE_ADMIN_OR_OWNER,
)

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""


volumes_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""List volumes.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-volumes'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'create',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Create volume.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'POST',
               'path': '/os-volumes'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'detail',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""List volumes detail.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-volumes/detail'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""Show volume.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-volumes/{volume_id}'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Delete volume.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'DELETE',
               'path': '/os-volumes/{volume_id}'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'snapshots:list',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""List snapshots.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-snapshots'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'snapshots:create',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Create snapshots.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'POST',
               'path': '/os-snapshots'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
            name=POLICY_NAME % 'snapshots:detail',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""List snapshots details.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-snapshots/detail'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'snapshots:show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="""Show snapshot.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'GET',
               'path': '/os-snapshots/{snapshot_id}'
           },
        ],
        scope_types=['system', 'project'],
        deprecated_rule=DEPRECATED_POLICY,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='22.0.0'),
    policy.DocumentedRuleDefault(
        name=POLICY_NAME % 'snapshots:delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="""Delete snapshot.

This API is a proxy call to the Volume service. It is deprecated.""",
       operations=[
           {
               'method': 'DELETE',
               'path': '/os-snapshots/{snapshot_id}'
           }
      ],
      scope_types=['system', 'project'],
      deprecated_rule=DEPRECATED_POLICY,
      deprecated_reason=DEPRECATED_REASON,
      deprecated_since='22.0.0'),
]


def list_rules():
    return volumes_policies
