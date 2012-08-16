# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Cloudbase Solutions Srl
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
Constants used in ops classes
"""

from nova.compute import power_state

HYPERV_VM_STATE_ENABLED = 2
HYPERV_VM_STATE_DISABLED = 3
HYPERV_VM_STATE_REBOOT = 10
HYPERV_VM_STATE_RESET = 11
HYPERV_VM_STATE_PAUSED = 32768
HYPERV_VM_STATE_SUSPENDED = 32769

HYPERV_POWER_STATE = {
    HYPERV_VM_STATE_DISABLED: power_state.SHUTDOWN,
    HYPERV_VM_STATE_ENABLED: power_state.RUNNING,
    HYPERV_VM_STATE_PAUSED: power_state.PAUSED,
    HYPERV_VM_STATE_SUSPENDED: power_state.SUSPENDED
}

REQ_POWER_STATE = {
    'Enabled': HYPERV_VM_STATE_ENABLED,
    'Disabled': HYPERV_VM_STATE_DISABLED,
    'Reboot': HYPERV_VM_STATE_REBOOT,
    'Reset': HYPERV_VM_STATE_RESET,
    'Paused': HYPERV_VM_STATE_PAUSED,
    'Suspended': HYPERV_VM_STATE_SUSPENDED,
}

WMI_JOB_STATUS_STARTED = 4096
WMI_JOB_STATE_RUNNING = 4
WMI_JOB_STATE_COMPLETED = 7

VM_SUMMARY_NUM_PROCS = 4
VM_SUMMARY_ENABLED_STATE = 100
VM_SUMMARY_MEMORY_USAGE = 103
VM_SUMMARY_UPTIME = 105
