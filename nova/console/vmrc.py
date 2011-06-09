# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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

"""VMRC console drivers."""

import base64
import json

from nova import exception
from nova import flags
from nova import log as logging
from nova.virt.vmwareapi import vim_util


FLAGS = flags.FLAGS
flags.DEFINE_integer('console_vmrc_port',
                     443,
                     "port for VMware VMRC connections")
flags.DEFINE_integer('console_vmrc_error_retries',
                     10,
                     "number of retries for retrieving VMRC information")


class VMRCConsole(object):
    """VMRC console driver with ESX credentials."""

    def __init__(self):
        super(VMRCConsole, self).__init__()

    @property
    def console_type(self):
        return 'vmrc+credentials'

    def get_port(self, context):
        """Get available port for consoles."""
        return FLAGS.console_vmrc_port

    def setup_console(self, context, console):
        """Sets up console."""
        pass

    def teardown_console(self, context, console):
        """Tears down console."""
        pass

    def init_host(self):
        """Perform console initialization."""
        pass

    def fix_pool_password(self, password):
        """Encode password."""
        # TODO(sateesh): Encrypt pool password
        return password

    def generate_password(self, vim_session, pool, instance_name):
        """Returns VMRC Connection credentials.

        Return string is of the form '<VM PATH>:<ESX Username>@<ESX Password>'.

        """
        username, password = pool['username'], pool['password']
        vms = vim_session._call_method(vim_util, 'get_objects',
                    'VirtualMachine', ['name', 'config.files.vmPathName'])
        vm_ds_path_name = None
        vm_ref = None
        for vm in vms:
            vm_name = None
            ds_path_name = None
            for prop in vm.propSet:
                if prop.name == 'name':
                    vm_name = prop.val
                elif prop.name == 'config.files.vmPathName':
                    ds_path_name = prop.val
            if vm_name == instance_name:
                vm_ref = vm.obj
                vm_ds_path_name = ds_path_name
                break
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        json_data = json.dumps({'vm_id': vm_ds_path_name,
                    'username': username,
                    'password': password})
        return base64.b64encode(json_data)

    def is_otp(self):
        """Is one time password or not."""
        return False


class VMRCSessionConsole(VMRCConsole):
    """VMRC console driver with VMRC One Time Sessions."""

    def __init__(self):
        super(VMRCSessionConsole, self).__init__()

    @property
    def console_type(self):
        return 'vmrc+session'

    def generate_password(self, vim_session, pool, instance_name):
        """Returns a VMRC Session.

        Return string is of the form '<VM MOID>:<VMRC Ticket>'.

        """
        vms = vim_session._call_method(vim_util, 'get_objects',
                    'VirtualMachine', ['name'])
        vm_ref = None
        for vm in vms:
            if vm.propSet[0].val == instance_name:
                vm_ref = vm.obj
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        virtual_machine_ticket = \
                        vim_session._call_method(
            vim_session._get_vim(),
            'AcquireCloneTicket',
            vim_session._get_vim().get_service_content().sessionManager)
        json_data = json.dumps({'vm_id': str(vm_ref.value),
                     'username': virtual_machine_ticket,
                     'password': virtual_machine_ticket})
        return base64.b64encode(json_data)

    def is_otp(self):
        """Is one time password or not."""
        return True
