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
        servers.list_rules()
    )
