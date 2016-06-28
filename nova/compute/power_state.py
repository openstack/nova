# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""Power state is the state we get by calling virt driver on a particular
domain. The hypervisor is always considered the authority on the status
of a particular VM, and the power_state in the DB should be viewed as a
snapshot of the VMs's state in the (recent) past. It can be periodically
updated, and should also be updated at the end of a task if the task is
supposed to affect power_state.
"""

from nova.objects import fields

# NOTE(maoy): These are *not* virDomainState values from libvirt.
# The hex value happens to match virDomainState for backward-compatibility
# reasons.
NOSTATE = fields.InstancePowerState.index(fields.InstancePowerState.NOSTATE)
RUNNING = fields.InstancePowerState.index(fields.InstancePowerState.RUNNING)
PAUSED = fields.InstancePowerState.index(fields.InstancePowerState.PAUSED)
# the VM is powered off
SHUTDOWN = fields.InstancePowerState.index(fields.InstancePowerState.SHUTDOWN)
CRASHED = fields.InstancePowerState.index(fields.InstancePowerState.CRASHED)
SUSPENDED = fields.InstancePowerState.index(
    fields.InstancePowerState.SUSPENDED)

# TODO(justinsb): Power state really needs to be a proper class,
# so that we're not locked into the libvirt status codes and can put mapping
# logic here rather than spread throughout the code
STATE_MAP = {fields.InstancePowerState.index(state): state
             for state in fields.InstancePowerState.ALL
             if state != fields.InstancePowerState._UNUSED}
