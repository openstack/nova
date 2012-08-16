# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 Pedro Navarro Perez
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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

import subprocess
import sys
import time

from nova import block_device
from nova import flags
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import vmutils

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import _winreg

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class VolumeUtils(object):
        def execute(self, *args, **kwargs):
            proc = subprocess.Popen(
                [args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            stdout_value, stderr_value = proc.communicate()
            if stdout_value.find('The operation completed successfully') == -1:
                raise vmutils.HyperVException(_('An error has occurred when '
                    'calling the iscsi initiator: %s') % stdout_value)

        def get_iscsi_initiator(self, cim_conn):
            """Get iscsi initiator name for this machine"""

            computer_system = cim_conn.Win32_ComputerSystem()[0]
            hostname = computer_system.name
            keypath = \
               r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\iSCSI\Discovery"
            try:
                key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, keypath, 0,
                    _winreg.KEY_ALL_ACCESS)
                temp = _winreg.QueryValueEx(key, 'DefaultInitiatorName')
                initiator_name = str(temp[0])
                _winreg.CloseKey(key)
            except Exception:
                LOG.info(_("The ISCSI initiator name can't be found. "
                    "Choosing the default one"))
                computer_system = cim_conn.Win32_ComputerSystem()[0]
                initiator_name = "iqn.1991-05.com.microsoft:" + \
                    hostname.lower()
            return {
                'ip': FLAGS.my_ip,
                'initiator': initiator_name,
            }

        def login_storage_target(self, target_lun, target_iqn, target_portal):
            """Add target portal, list targets and logins to the target"""
            separator = target_portal.find(':')
            target_address = target_portal[:separator]
            target_port = target_portal[separator + 1:]
            #Adding target portal to iscsi initiator. Sending targets
            self.execute('iscsicli.exe ' + 'AddTargetPortal ' +
                target_address + ' ' + target_port +
                ' * * * * * * * * * * * * *')
            #Listing targets
            self.execute('iscsicli.exe ' + 'LisTargets')
            #Sending login
            self.execute('iscsicli.exe ' + 'qlogintarget ' + target_iqn)
            #Waiting the disk to be mounted. Research this
            time.sleep(FLAGS.hyperv_wait_between_attach_retry)

        def logout_storage_target(self, _conn_wmi, target_iqn):
            """ Logs out storage target through its session id """

            sessions = _conn_wmi.query(
                    "SELECT * FROM MSiSCSIInitiator_SessionClass \
                    WHERE TargetName='" + target_iqn + "'")
            for session in sessions:
                self.execute_log_out(session.SessionId)

        def execute_log_out(self, session_id):
            """ Executes log out of the session described by its session ID """
            self.execute('iscsicli.exe ' + 'logouttarget ' + session_id)

        def volume_in_mapping(self, mount_device, block_device_info):
            block_device_list = [block_device.strip_dev(vol['mount_device'])
                                 for vol in
                                 driver.block_device_info_get_mapping(
                                     block_device_info)]
            swap = driver.block_device_info_get_swap(block_device_info)
            if driver.swap_is_usable(swap):
                block_device_list.append(
                    block_device.strip_dev(swap['device_name']))
            block_device_list += [block_device.strip_dev(
                ephemeral['device_name'])
                for ephemeral in
                driver.block_device_info_get_ephemerals(block_device_info)]

            LOG.debug(_("block_device_list %s"), block_device_list)
            return block_device.strip_dev(mount_device) in block_device_list
