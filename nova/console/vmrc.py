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

"""
VMRC console drivers.
"""

from nova import flags
from nova import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi_conn import VMWareAPISession

flags.DEFINE_integer('console_vmrc_port',
                     443,
                     "port for VMware VMRC connections")
flags.DEFINE_integer('console_vmrc_error_retries',
                     10,
                     "number of retries for retrieving VMRC information")

FLAGS = flags.FLAGS


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
        #TODO:Encrypt pool password
        return password

    def generate_password(self, address, username, password, instance_name):
        """Returns a VMRC Connection credentials
        Return string is of the form '<VM MOID>:<ESX Username>@<ESX Password>'.
        """
        vim_session = VMWareAPISession(address,
                                       username,
                                       password,
                                       FLAGS.console_vmrc_error_retries)
        vms = vim_session._call_method(vim_util, "get_objects",
                    "VirtualMachine", ["name"])
        vm_ref = None
        for vm in vms:
            if vm.propSet[0].val == instance_name:
                vm_ref = vm.obj
        if vm_ref is None:
            raise Exception(_("instance - %s not present") % instance_name)
        return str(vm_ref) + ":" + username + "@" + password

    def is_otp(self):
        """Is one time password."""
        return False


class VMRCSessionConsole(VMRCConsole):
    """VMRC console driver with VMRC One Time Sessions"""

    def __init__(self):
        super(VMRCSessionConsole, self).__init__()

    @property
    def console_type(self):
        return 'vmrc+session'

    def generate_password(self, address, username, password, instance_name):
        """Returns a VMRC Session
        Return string is of the form '<VM MOID>:<VMRC Ticket>'.
        """
        vim_session = VMWareAPISession(address,
                                       username,
                                       password,
                                       FLAGS.console_vmrc_error_retries)
        vms = vim_session._call_method(vim_util, "get_objects",
                    "VirtualMachine", ["name"])
        vm_ref = None
        for vm in vms:
            if vm.propSet[0].val == instance_name:
                vm_ref = vm.obj
        if vm_ref is None:
            raise Exception(_("instance - %s not present") % instance_name)
        virtual_machine_ticket = \
                        vim_session._call_method(
            vim_session._get_vim(),
            "AcquireCloneTicket",
            vim_session._get_vim().get_service_content().sessionManager)
        return str(vm_ref) + ":" + virtual_machine_ticket

    def is_otp(self):
        """Is one time password."""
        return True
