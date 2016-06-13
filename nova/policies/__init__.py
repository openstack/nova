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


import itertools

from nova.policies import access_ips
from nova.policies import admin_actions
from nova.policies import admin_password
from nova.policies import agents
from nova.policies import aggregates
from nova.policies import assisted_volume_snapshots
from nova.policies import attach_interfaces
from nova.policies import availability_zone
from nova.policies import baremetal_nodes
from nova.policies import base
from nova.policies import block_device_mapping_v1
from nova.policies import cells
from nova.policies import certificates
from nova.policies import cloudpipe
from nova.policies import config_drive
from nova.policies import console_auth_tokens
from nova.policies import console_output
from nova.policies import consoles
from nova.policies import create_backup
from nova.policies import deferred_delete
from nova.policies import evacuate
from nova.policies import extended_availability_zone
from nova.policies import extended_server_attributes
from nova.policies import extended_status
from nova.policies import extended_volumes
from nova.policies import extension_info
from nova.policies import extensions
from nova.policies import fixed_ips
from nova.policies import flavor_access
from nova.policies import flavor_extra_specs
from nova.policies import flavor_manage
from nova.policies import flavor_rxtx
from nova.policies import flavors
from nova.policies import floating_ip_dns
from nova.policies import floating_ip_pools
from nova.policies import floating_ips
from nova.policies import floating_ips_bulk
from nova.policies import fping
from nova.policies import hide_server_addresses
from nova.policies import hosts
from nova.policies import hypervisors
from nova.policies import image_size
from nova.policies import images
from nova.policies import instance_actions
from nova.policies import instance_usage_audit_log
from nova.policies import ips
from nova.policies import keypairs
from nova.policies import limits
from nova.policies import lock_server
from nova.policies import migrate_server
from nova.policies import migrations
from nova.policies import multinic
from nova.policies import networks
from nova.policies import networks_associate
from nova.policies import servers


def list_rules():
    return itertools.chain(
        access_ips.list_rules(),
        admin_actions.list_rules(),
        admin_password.list_rules(),
        agents.list_rules(),
        aggregates.list_rules(),
        assisted_volume_snapshots.list_rules(),
        attach_interfaces.list_rules(),
        availability_zone.list_rules(),
        baremetal_nodes.list_rules(),
        base.list_rules(),
        block_device_mapping_v1.list_rules(),
        cells.list_rules(),
        certificates.list_rules(),
        cloudpipe.list_rules(),
        config_drive.list_rules(),
        console_auth_tokens.list_rules(),
        console_output.list_rules(),
        consoles.list_rules(),
        create_backup.list_rules(),
        deferred_delete.list_rules(),
        evacuate.list_rules(),
        extended_availability_zone.list_rules(),
        extended_server_attributes.list_rules(),
        extended_status.list_rules(),
        extended_volumes.list_rules(),
        extension_info.list_rules(),
        extensions.list_rules(),
        fixed_ips.list_rules(),
        flavor_access.list_rules(),
        flavor_extra_specs.list_rules(),
        flavor_manage.list_rules(),
        flavor_rxtx.list_rules(),
        flavors.list_rules(),
        floating_ip_dns.list_rules(),
        floating_ip_pools.list_rules(),
        floating_ips.list_rules(),
        floating_ips_bulk.list_rules(),
        fping.list_rules(),
        hide_server_addresses.list_rules(),
        hosts.list_rules(),
        hypervisors.list_rules(),
        image_size.list_rules(),
        images.list_rules(),
        instance_actions.list_rules(),
        instance_usage_audit_log.list_rules(),
        ips.list_rules(),
        keypairs.list_rules(),
        limits.list_rules(),
        lock_server.list_rules(),
        migrate_server.list_rules(),
        migrations.list_rules(),
        multinic.list_rules(),
        networks.list_rules(),
        networks_associate.list_rules(),
        servers.list_rules()
    )
