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

import sys

from nova.virt.hyperv import rdpconsoleutils

if sys.platform == 'win32':
    import wmi


class RDPConsoleUtilsV2(rdpconsoleutils.RDPConsoleUtils):
    def __init__(self):
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization/v2')

    def get_rdp_console_port(self):
        rdp_setting_data = self._conn.Msvm_TerminalServiceSettingData()[0]
        return rdp_setting_data.ListenerPort
