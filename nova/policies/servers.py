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


from nova.policies import base


RULE_AOO = base.RULE_ADMIN_OR_OWNER
SERVERS = 'os_compute_api:servers:%s'

rules = [
    base.create_rule_default(
        SERVERS % 'index',
        RULE_AOO,
        "List all servers",
        [
            {
                'method': 'GET',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'detail',
        RULE_AOO,
        "List all servers with detailed information",
        [
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'index:get_all_tenants',
        base.RULE_ADMIN_API,
        "List all servers for all projects",
        [
            {
                'method': 'GET',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'detail:get_all_tenants',
        base.RULE_ADMIN_API,
        "List all servers with detailed information for all projects",
        [
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'show',
        RULE_AOO,
        "Show a server",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            }
        ]),
    # the details in host_status are pretty sensitive, only admins
    # should do that by default.
    base.create_rule_default(
        SERVERS % 'show:host_status',
        base.RULE_ADMIN_API,
        "Show a server with additional host status information",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create',
        RULE_AOO,
        "Create a server",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create:forced_host',
        base.RULE_ADMIN_API,
        "Create a server on the specified host",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create:attach_volume',
        RULE_AOO,
        "Create a server with the requested volume attached to it",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create:attach_network',
        RULE_AOO,
        "Create a server with the requested network attached to it",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'delete',
        RULE_AOO,
        "Delete a server",
        [
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'update',
        RULE_AOO,
        "Update a server",
        [
            {
                'method': 'PUT',
                'path': '/servers/{server_id}'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'confirm_resize',
        RULE_AOO,
        "Confirm a server resize",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (confirmResize)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'revert_resize',
        RULE_AOO,
        "Revert a server resize",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (revertResize)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'reboot',
        RULE_AOO,
        "Reboot a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (reboot)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'resize',
        RULE_AOO,
        "Resize a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resize)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'rebuild',
        RULE_AOO,
        "Rebuild a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create_image',
        RULE_AOO,
        "Create an image from a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'create_image:allow_volume_backed',
        RULE_AOO,
        "Create an image from a volume backed server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'start',
        RULE_AOO,
        "Start a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-start)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'stop',
        RULE_AOO,
        "Stop a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-stop)'
            }
        ]),
    base.create_rule_default(
        SERVERS % 'trigger_crash_dump',
        RULE_AOO,
        "Trigger crash dump in a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (trigger_crash_dump)'
            }
        ]),
]


def list_rules():
    return rules
