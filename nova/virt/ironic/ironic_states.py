# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2010 OpenStack Foundation
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

"""
Mapping of bare metal node states.

A node may have empty {} `properties` and `driver_info` in which case, it is
said to be "initialized" but "not available", and the state is NOSTATE.

When updating `properties`,  any data will be rejected if the data fails to be
validated by the driver. Any node with non-empty `properties` is said to be
"initialized", and the state is INIT.

When the driver has received both `properties` and `driver_info`, it will check
the power status of the node and update the `power_state` accordingly. If the
driver fails to read the power state from the node, it will reject the
`driver_info` change, and the state will remain as INIT. If the power status
check succeeds, `power_state` will change to one of POWER_ON or POWER_OFF,
accordingly.

At this point, the power state may be changed via the API, a console
may be started, and a tenant may be associated.

The `power_state` for a node always represents the current power state. Any
power operation sets this to the actual state when done (whether successful or
not). It is set to ERROR only when unable to get the power state from a node.

When `instance_uuid` is set to a non-empty / non-None value, the node is said
to be "associated" with a tenant.

An associated node can not be deleted.

The `instance_uuid` field may be unset only if the node is in POWER_OFF or
ERROR states.
"""

NOSTATE = None
INIT = 'initializing'
ACTIVE = 'active'
BUILDING = 'building'
DEPLOYWAIT = 'wait call-back'
DEPLOYING = 'deploying'
DEPLOYFAIL = 'deploy failed'
DEPLOYDONE = 'deploy complete'
DELETING = 'deleting'
DELETED = 'deleted'
ERROR = 'error'
REBUILD = 'rebuild'

POWER_ON = 'power on'
POWER_OFF = 'power off'
REBOOT = 'rebooting'
SUSPEND = 'suspended'
