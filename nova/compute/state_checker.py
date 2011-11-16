# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

from nova import db
from nova.compute import task_states as ts
from nova.compute import vm_states as vm
from nova import context as ctxt

# Function names that run the state check before their execution:
REBOOT = 'reboot'
START = 'start'
REBUILD = 'rebuild'
STOP = 'stop'
PAUSE = 'pause'
BACKUP = 'backup'
UNPAUSE = 'unpause'
SUSPEND = 'suspend'
RESUME = 'resume'
RESCUE = 'rescue'
UNRESCUE = 'unrescue'
SNAPSHOT = 'snapshot'
RESIZE = 'resize'
CONFIRM_RESIZE = 'confirm_resize'
REVERT_RESIZE = 'revert_resize'
DELETE = 'delete'
SOFT_DELETE = 'soft_delete'
FORCE_DELETE = 'force_delete'
RESTORE = 'restore'


# Aux variables to save cpu time, used by blocker dictionaries
all_ts_but_resize_verify = list(set(ts.get_list()) - set([ts.RESIZE_VERIFY]))
all_vm_but_act_resc = list(set(vm.get_list()) - set([vm.ACTIVE, vm.RESCUED]))
all_vm_but_active = list(set(vm.get_list()) - set([vm.ACTIVE]))

# Call blocked if the vm task_state is found in the corresponding list
block_for_task_state = {
    REBOOT: all_ts_but_resize_verify,
    START: all_ts_but_resize_verify,
    REBUILD: all_ts_but_resize_verify,
    PAUSE: all_ts_but_resize_verify,
    STOP: all_ts_but_resize_verify,
    UNPAUSE: all_ts_but_resize_verify,
    SUSPEND: all_ts_but_resize_verify,
    RESUME: all_ts_but_resize_verify,
    RESCUE: all_ts_but_resize_verify,
    UNRESCUE: all_ts_but_resize_verify,
    SNAPSHOT: all_ts_but_resize_verify,
    BACKUP: all_ts_but_resize_verify,
    RESIZE: all_ts_but_resize_verify,
    CONFIRM_RESIZE: all_ts_but_resize_verify,
    REVERT_RESIZE: all_ts_but_resize_verify}

# Call blocked if the vm vm_state is found in the corresponding list
block_for_vm_state = {
    REBOOT: all_vm_but_act_resc,
    START: list(set(vm.get_list()) - set([vm.STOPPED])),
    REBUILD: all_vm_but_active,
    PAUSE: all_vm_but_act_resc,
    STOP: all_vm_but_act_resc,
    UNPAUSE: list(set(vm.get_list()) - set([vm.PAUSED])),
    SUSPEND: all_vm_but_act_resc,
    RESUME: list(set(vm.get_list()) - set([vm.SUSPENDED])),
    RESCUE: list(set(vm.get_list()) - set([vm.ACTIVE, vm.STOPPED])),
    UNRESCUE: list(set(vm.get_list()) - set([vm.ACTIVE, vm.RESCUED])),
    SNAPSHOT: all_vm_but_active,
    BACKUP: all_vm_but_active,
    RESIZE: all_vm_but_active,
    CONFIRM_RESIZE: all_vm_but_active,
    REVERT_RESIZE: all_vm_but_active}

# Call blocked if the combination of vm_state, power_state and task_state is
# found in the corresponding list
block_for_combination = {
    CONFIRM_RESIZE: [{'vm_state': vm.ACTIVE, 'task_state': None}],
    REVERT_RESIZE: [{'vm_state': vm.ACTIVE, 'task_state': None}]}


def is_blocked(method_name, context, instance_ref):
    """
    Is the method blocked for the VM state?

    This method returns False if the state of the vm is found
    in the blocked dictionaries for the method.
    """
    if instance_ref['task_state'] in block_for_task_state.get(method_name, ()):
        return True
    if instance_ref['vm_state'] in block_for_vm_state.get(method_name, ()):
        return True
    if method_name in block_for_combination:
        return _is_combination_blocked(method_name, instance_ref)
    # Allow the method if not found in any list
    return False


def _is_combination_blocked(method_name, instance_ref):
    """
    Is the method blocked according to the blocked_combination dictionary?

    To be blocked, all the elements
    in a dictionary need to match the vm states.
    If a value is not present in a dictionary we assume that the dictionary
    applies for any value of that particular element
    """
    for blocked_element in block_for_combination[method_name]:
        # Check power state
        if 'power_state' in blocked_element and instance_ref['power_state']\
            != blocked_element['power_state']:
            continue
        # Check vm state
        if 'vm_state' in blocked_element and instance_ref['vm_state']\
            != blocked_element['vm_state']:
            continue
        # Check task state
        if 'task_state' in blocked_element and instance_ref['task_state']\
            != blocked_element['task_state']:
            continue
        return True
    # After analyzing all the dictionaries for the method, none tells us to
    # block the function
    return False
