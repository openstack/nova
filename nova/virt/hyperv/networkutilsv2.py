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
Based on the "root/virtualization/v2" namespace available starting with
Hyper-V Server / Windows Server 2012.
"""

import sys

if sys.platform == 'win32':
    import wmi

from nova.i18n import _
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import vmutils


class NetworkUtilsV2(networkutils.NetworkUtils):
    def __init__(self):
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization/v2')

    def get_external_vswitch(self, vswitch_name):
        if vswitch_name:
            vswitches = self._conn.Msvm_VirtualEthernetSwitch(
                ElementName=vswitch_name)
            if not len(vswitches):
                raise vmutils.HyperVException(_('vswitch "%s" not found')
                                              % vswitch_name)
        else:
            # Find the vswitch that is connected to the first physical nic.
            ext_port = self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')[0]
            lep = ext_port.associators(wmi_result_class='Msvm_LANEndpoint')[0]
            lep1 = lep.associators(wmi_result_class='Msvm_LANEndpoint')[0]
            esw = lep1.associators(
                wmi_result_class='Msvm_EthernetSwitchPort')[0]
            vswitches = esw.associators(
                wmi_result_class='Msvm_VirtualEthernetSwitch')

            if not len(vswitches):
                raise vmutils.HyperVException(_('No external vswitch found'))

        return vswitches[0].path_()

    def create_vswitch_port(self, vswitch_path, port_name):
        raise NotImplementedError()

    def vswitch_port_needed(self):
        return False
