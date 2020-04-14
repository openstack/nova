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


RULE_AOO = base.RULE_ADMIN_OR_OWNER
SERVERS = 'os_compute_api:servers:%s'
NETWORK_ATTACH_EXTERNAL = 'network:attach_external_network'
ZERO_DISK_FLAVOR = SERVERS % 'create:zero_disk_flavor'
REQUESTED_DESTINATION = 'compute:servers:create:requested_destination'
CROSS_CELL_RESIZE = 'compute:servers:resize:cross_cell'

rules = [
    policy.DocumentedRuleDefault(
        name=SERVERS % 'index',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List all servers",
        operations=[
            {
                'method': 'GET',
                'path': '/servers'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'detail',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="List all servers with detailed information",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'index:get_all_tenants',
        check_str=base.SYSTEM_READER,
        description="List all servers for all projects",
        operations=[
            {
                'method': 'GET',
                'path': '/servers'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'detail:get_all_tenants',
        check_str=base.SYSTEM_READER,
        description="List all servers with detailed information for "
        " all projects",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'allow_all_filters',
        check_str=base.SYSTEM_READER,
        description="Allow all filters when listing servers",
        operations=[
            {
                'method': 'GET',
                'path': '/servers'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ],
        scope_types=['system']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'show',
        check_str=base.PROJECT_READER_OR_SYSTEM_READER,
        description="Show a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            }
        ],
        scope_types=['system', 'project']),
    # the details in host_status are pretty sensitive, only admins
    # should do that by default.
    policy.DocumentedRuleDefault(
        name=SERVERS % 'show:host_status',
        check_str=base.SYSTEM_ADMIN,
        description="""
Show a server with additional host status information.

This means host_status will be shown irrespective of status value. If showing
only host_status UNKNOWN is desired, use the
``os_compute_api:servers:show:host_status:unknown-only`` policy rule.

Microvision 2.75 added the ``host_status`` attribute in the
``PUT /servers/{server_id}`` and ``POST /servers/{server_id}/action (rebuild)``
API responses which are also controlled by this policy rule, like the
``GET /servers*`` APIs.
""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
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
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'show:host_status:unknown-only',
        check_str=base.SYSTEM_ADMIN,
        description="""
Show a server with additional host status information, only if host status is
UNKNOWN.

This policy rule will only be enforced when the
``os_compute_api:servers:show:host_status`` policy rule does not pass for the
request. An example policy configuration could be where the
``os_compute_api:servers:show:host_status`` rule is set to allow admin-only and
the ``os_compute_api:servers:show:host_status:unknown-only`` rule is set to
allow everyone.
""",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
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
        scope_types=['system', 'project'],),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create',
        check_str=base.PROJECT_MEMBER,
        description="Create a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create:forced_host',
        # TODO(gmann): We need to make it SYSTEM_ADMIN.
        # PROJECT_ADMIN is added for now because create server
        # policy is project scoped and there is no way to
        # pass the project_id in request body for system scoped
        # roles so that create server for other project with force host.
        # To achieve that, we need to update the create server API to
        # accept the project_id for whom the server needs to be created
        # and then change the scope of this policy to system-only
        # Because that is API change it needs to be done with new
        # microversion.
        check_str=base.PROJECT_ADMIN,
        description="""
Create a server on the specified host and/or node.

In this case, the server is forced to launch on the specified
host and/or node by bypassing the scheduler filters unlike the
``compute:servers:create:requested_destination`` rule.
""",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=REQUESTED_DESTINATION,
        check_str=base.RULE_ADMIN_API,
        description="""
Create a server on the requested compute service host and/or
hypervisor_hostname.

In this case, the requested host and/or hypervisor_hostname is
validated by the scheduler filters unlike the
``os_compute_api:servers:create:forced_host`` rule.
""",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create:attach_volume',
        check_str=base.PROJECT_MEMBER,
        description="Create a server with the requested volume attached to it",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create:attach_network',
        check_str=base.PROJECT_MEMBER,
        description="Create a server with the requested network attached "
        " to it",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create:trusted_certs',
        check_str=base.PROJECT_MEMBER,
        description="Create a server with trusted image certificate IDs",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project']),
    policy.DocumentedRuleDefault(
        name=ZERO_DISK_FLAVOR,
        # TODO(gmann): We need to make it SYSTEM_ADMIN.
        # PROJECT_ADMIN is added for now because create server
        # policy is project scoped and there is no way to
        # pass the project_id in request body for system scoped
        # roles so that create server for other project with zero disk flavor.
        # To achieve that, we need to update the create server API to
        # accept the project_id for whom the server needs to be created
        # and then change the scope of this policy to system-only
        # Because that is API change it needs to be done with new
        # microversion.
        check_str=base.PROJECT_ADMIN,
        description="""
This rule controls the compute API validation behavior of creating a server
with a flavor that has 0 disk, indicating the server should be volume-backed.

For a flavor with disk=0, the root disk will be set to exactly the size of the
image used to deploy the instance. However, in this case the filter_scheduler
cannot select the compute host based on the virtual image size. Therefore, 0
should only be used for volume booted instances or for testing purposes.

WARNING: It is a potential security exposure to enable this policy rule
if users can upload their own images since repeated attempts to
create a disk=0 flavor instance with a large image can exhaust
the local disk of the compute (or shared storage cluster). See bug
https://bugs.launchpad.net/nova/+bug/1739646 for details.
""",
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=NETWORK_ATTACH_EXTERNAL,
        # TODO(gmann): We need to make it SYSTEM_ADMIN.
        # PROJECT_ADMIN is added for now because create server
        # policy is project scoped and there is no way to
        # pass the project_id in request body for system scoped
        # roles so that create server for other project or attach the
        # external network. To achieve that, we need to update the
        # create server API to accept the project_id for whom the
        # server needs to be created and then change the scope of this
        # policy to system-only Because that is API change it needs to
        # be done with new microversion.
        check_str=base.PROJECT_ADMIN,
        description="Attach an unshared external network to a server",
        operations=[
            # Create a server with a requested network or port.
            {
                'method': 'POST',
                'path': '/servers'
            },
            # Attach a network or port to an existing server.
            {
                'method': 'POST',
                'path': '/servers/{server_id}/os-interface'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'delete',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Delete a server",
        operations=[
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'update',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Update a server",
        operations=[
            {
                'method': 'PUT',
                'path': '/servers/{server_id}'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'confirm_resize',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Confirm a server resize",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (confirmResize)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'revert_resize',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Revert a server resize",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (revertResize)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'reboot',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Reboot a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (reboot)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'resize',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Resize a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resize)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=CROSS_CELL_RESIZE,
        check_str=base.RULE_NOBODY,
        description="Resize a server across cells. By default, this is "
        "disabled for all users and recommended to be tested in a "
        "deployment for admin users before opening it up to non-admin users. "
        "Resizing within a cell is the default preferred behavior even if "
        "this is enabled. ",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resize)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'rebuild',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Rebuild a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'rebuild:trusted_certs',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Rebuild a server with trusted image certificate IDs",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create_image',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Create an image from a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'create_image:allow_volume_backed',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Create an image from a volume backed server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'start',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Start a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-start)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'stop',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Stop a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-stop)'
            }
        ],
        scope_types=['system', 'project']),
    policy.DocumentedRuleDefault(
        name=SERVERS % 'trigger_crash_dump',
        check_str=base.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        description="Trigger crash dump in a server",
        operations=[
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (trigger_crash_dump)'
            }
        ],
        scope_types=['system', 'project']),
]


def list_rules():
    return rules
