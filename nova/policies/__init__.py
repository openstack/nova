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
        servers.list_rules()
    )
