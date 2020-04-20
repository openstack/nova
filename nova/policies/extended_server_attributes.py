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


BASE_POLICY_NAME = 'os_compute_api:os-extended-server-attributes'


extended_server_attributes_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME,
        check_str=base.SYSTEM_ADMIN,
        description="""Return extended attributes for server.

This rule will control the visibility for a set of servers attributes:

- ``OS-EXT-SRV-ATTR:host``
- ``OS-EXT-SRV-ATTR:instance_name``
- ``OS-EXT-SRV-ATTR:reservation_id`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:launch_index`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:hostname`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:kernel_id`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:ramdisk_id`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:root_device_name`` (since microversion 2.3)
- ``OS-EXT-SRV-ATTR:user_data`` (since microversion 2.3)

Microvision 2.75 added the above attributes in the ``PUT /servers/{server_id}``
and ``POST /servers/{server_id}/action (rebuild)`` API responses which are
also controlled by this policy rule, like the ``GET /servers*`` APIs.
""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{id}'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            },
            {
                'method': 'PUT',
                'path': '/servers/{server_id}'
            },
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ],
        scope_types=['system', 'project']
    ),
]


def list_rules():
    return extended_server_attributes_policies
