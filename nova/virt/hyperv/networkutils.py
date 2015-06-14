# Copyright 2013 Cloudbase Solutions Srl
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
Utility class for network related operations.
"""

import sys
import uuid

if sys.platform == 'win32':
    import wmi

from nova.i18n import _
from nova.virt.hyperv import vmutils


class NetworkUtils(object):
    def __init__(self):
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization')

    def get_external_vswitch(self, vswitch_name):
        if vswitch_name:
            vswitches = self._conn.Msvm_VirtualSwitch(ElementName=vswitch_name)
        else:
            # Find the vswitch that is connected to the first physical nic.
            ext_port = self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')[0]
            port = ext_port.associators(wmi_result_class='Msvm_SwitchPort')[0]
            vswitches = port.associators(wmi_result_class='Msvm_VirtualSwitch')

        if not len(vswitches):
            raise vmutils.HyperVException(_('vswitch "%s" not found')
                                          % vswitch_name)
        return vswitches[0].path_()

    def create_vswitch_port(self, vswitch_path, port_name):
        switch_svc = self._conn.Msvm_VirtualSwitchManagementService()[0]
        # Create a port on the vswitch.
        (new_port, ret_val) = switch_svc.CreateSwitchPort(
            Name=str(uuid.uuid4()),
            FriendlyName=port_name,
            ScopeOfResidence="",
            VirtualSwitch=vswitch_path)
        if ret_val != 0:
            raise vmutils.HyperVException(_("Failed to create vswitch port "
                                            "%(port_name)s on switch "
                                            "%(vswitch_path)s") %
                                          {'port_name': port_name,
                                           'vswitch_path': vswitch_path})
        return new_port

    def vswitch_port_needed(self):
        # NOTE(alexpilotti): In WMI V2 the vswitch_path is set in the VM
        # setting data without the need for a vswitch port.
        return True
