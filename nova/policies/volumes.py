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


volumes_policies = [
    policy.DocumentedRuleDefault(
        BASE_POLICY_NAME,
        base.RULE_ADMIN_OR_OWNER,
        """Manage volumes for use with the Compute API.

Lists, shows details, creates, and deletes volumes and
snapshots. These APIs are proxy calls to the Volume service.
These are all deprecated.
""",
       [
           {
               'method': 'GET',
               'path': '/os-volumes'
           },
           {
               'method': 'POST',
               'path': '/os-volumes'
           },
           {
               'method': 'GET',
               'path': '/os-volumes/detail'
           },
           {
               'method': 'GET',
               'path': '/os-volumes/{volume_id}'
           },
           {
               'method': 'DELETE',
               'path': '/os-volumes/{volume_id}'
           },
           {
               'method': 'GET',
               'path': '/os-snapshots'
           },
           {
               'method': 'POST',
               'path': '/os-snapshots'
           },
           {
               'method': 'GET',
               'path': '/os-snapshots/detail'
           },
           {
               'method': 'GET',
               'path': '/os-snapshots/{snapshot_id}'
           },
           {
               'method': 'DELETE',
               'path': '/os-snapshots/{snapshot_id}'
           }
      ]),
]


def list_rules():
    return volumes_policies
