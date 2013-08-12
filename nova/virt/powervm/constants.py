# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

from nova.compute import power_state

POWERVM_NOSTATE = ''
POWERVM_RUNNING = 'Running'
POWERVM_STARTING = 'Starting'
POWERVM_SHUTDOWN = 'Not Activated'
POWERVM_SHUTTING_DOWN = 'Shutting Down'
POWERVM_ERROR = 'Error'
POWERVM_NOT_AVAILABLE = 'Not Available'
POWERVM_OPEN_FIRMWARE = 'Open Firmware'
POWERVM_POWER_STATE = {
    POWERVM_NOSTATE: power_state.NOSTATE,
    POWERVM_RUNNING: power_state.RUNNING,
    POWERVM_STARTING: power_state.RUNNING,
    POWERVM_SHUTDOWN: power_state.SHUTDOWN,
    POWERVM_SHUTTING_DOWN: power_state.SHUTDOWN,
    POWERVM_ERROR: power_state.CRASHED,
    POWERVM_OPEN_FIRMWARE: power_state.CRASHED,
    POWERVM_NOT_AVAILABLE: power_state.CRASHED
}

POWERVM_CPU_INFO = ('ppc64', 'powervm', '3940')
POWERVM_HYPERVISOR_TYPE = 'powervm'
POWERVM_HYPERVISOR_VERSION = '7.1'
POWERVM_SUPPORTED_INSTANCES = [('ppc64', 'powervm', 'hvm')]

POWERVM_MIN_ROOT_GB = 10

POWERVM_MIN_MEM = 512
POWERVM_MAX_MEM = 1024
POWERVM_MAX_CPUS = 1
POWERVM_MIN_CPUS = 1
POWERVM_CONNECTION_TIMEOUT = 60

POWERVM_LPAR_OPERATION_TIMEOUT = 30
