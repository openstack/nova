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

from os_win import constants
from oslo_utils import units

from nova.compute import power_state
from nova.objects import fields as obj_fields

HYPERV_POWER_STATE = {
    constants.HYPERV_VM_STATE_DISABLED: power_state.SHUTDOWN,
    constants.HYPERV_VM_STATE_SHUTTING_DOWN: power_state.SHUTDOWN,
    constants.HYPERV_VM_STATE_ENABLED: power_state.RUNNING,
    constants.HYPERV_VM_STATE_PAUSED: power_state.PAUSED,
    constants.HYPERV_VM_STATE_SUSPENDED: power_state.SUSPENDED
}

WMI_WIN32_PROCESSOR_ARCHITECTURE = {
    constants.ARCH_I686: obj_fields.Architecture.I686,
    constants.ARCH_MIPS: obj_fields.Architecture.MIPS,
    constants.ARCH_ALPHA: obj_fields.Architecture.ALPHA,
    constants.ARCH_PPC: obj_fields.Architecture.PPC,
    constants.ARCH_ARMV7: obj_fields.Architecture.ARMV7,
    constants.ARCH_IA64: obj_fields.Architecture.IA64,
    constants.ARCH_X86_64: obj_fields.Architecture.X86_64,
}


CTRL_TYPE_IDE = "IDE"
CTRL_TYPE_SCSI = "SCSI"

DISK = "VHD"
DISK_FORMAT = DISK
DVD = "DVD"
DVD_FORMAT = "ISO"
VOLUME = "VOLUME"

DISK_FORMAT_MAP = {
    DISK_FORMAT.lower(): DISK,
    DVD_FORMAT.lower(): DVD
}

BDI_DEVICE_TYPE_TO_DRIVE_TYPE = {'disk': DISK}

DISK_FORMAT_VHD = "VHD"
DISK_FORMAT_VHDX = "VHDX"

HOST_POWER_ACTION_SHUTDOWN = "shutdown"
HOST_POWER_ACTION_REBOOT = "reboot"
HOST_POWER_ACTION_STARTUP = "startup"

FLAVOR_SPEC_SECURE_BOOT = "os:secure_boot"
IMAGE_PROP_VM_GEN_1 = "hyperv-gen1"
IMAGE_PROP_VM_GEN_2 = "hyperv-gen2"

VM_GEN_1 = 1
VM_GEN_2 = 2

SERIAL_CONSOLE_BUFFER_SIZE = 4 * units.Ki

SERIAL_PORT_TYPE_RO = 'ro'
SERIAL_PORT_TYPE_RW = 'rw'

# The default serial console port number used for
# logging and interactive sessions.
DEFAULT_SERIAL_CONSOLE_PORT = 1

FLAVOR_ESPEC_REMOTEFX_RES = 'os:resolution'
FLAVOR_ESPEC_REMOTEFX_MONITORS = 'os:monitors'
FLAVOR_ESPEC_REMOTEFX_VRAM = 'os:vram'

IOPS_BASE_SIZE = 8 * units.Ki

STORAGE_PROTOCOL_ISCSI = 'iscsi'
STORAGE_PROTOCOL_FC = 'fibre_channel'
STORAGE_PROTOCOL_SMBFS = 'smbfs'
