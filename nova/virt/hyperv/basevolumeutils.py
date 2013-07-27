# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 Pedro Navarro Perez
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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

import abc
import sys

if sys.platform == 'win32':
    import _winreg
    import wmi

from nova import block_device
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt import driver

LOG = logging.getLogger(__name__)


class BaseVolumeUtils(object):

    def __init__(self, host='.'):
        if sys.platform == 'win32':
            self._conn_wmi = wmi.WMI(moniker='//%s/root/wmi' % host)
            self._conn_cimv2 = wmi.WMI(moniker='//%s/root/cimv2' % host)

    @abc.abstractmethod
    def login_storage_target(self, target_lun, target_iqn, target_portal):
        pass

    @abc.abstractmethod
    def logout_storage_target(self, target_iqn):
        pass

    @abc.abstractmethod
    def execute_log_out(self, session_id):
        pass

    def get_iscsi_initiator(self):
        """Get iscsi initiator name for this machine."""

        computer_system = self._conn_cimv2.Win32_ComputerSystem()[0]
        hostname = computer_system.name
        keypath = ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                   "iSCSI\\Discovery")
        try:
            key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, keypath, 0,
                                  _winreg.KEY_ALL_ACCESS)
            temp = _winreg.QueryValueEx(key, 'DefaultInitiatorName')
            initiator_name = str(temp[0])
            _winreg.CloseKey(key)
        except Exception:
            LOG.info(_("The ISCSI initiator name can't be found. "
                       "Choosing the default one"))
            computer_system = self._conn_cimv2.Win32_ComputerSystem()[0]
            initiator_name = "iqn.1991-05.com.microsoft:" + hostname.lower()
        return initiator_name

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

    def _get_drive_number_from_disk_path(self, disk_path):
        # TODO(pnavarro) replace with regex
        start_device_id = disk_path.find('"', disk_path.find('DeviceID'))
        end_device_id = disk_path.find('"', start_device_id + 1)
        device_id = disk_path[start_device_id + 1:end_device_id]
        drive_number = device_id[device_id.find("\\") + 2:]
        if drive_number == 'NODRIVE':
            return None
        return int(drive_number)

    def get_session_id_from_mounted_disk(self, physical_drive_path):
        drive_number = self._get_drive_number_from_disk_path(
            physical_drive_path)
        if not drive_number:
            return None

        initiator_sessions = self._conn_wmi.query("SELECT * FROM "
                                                  "MSiSCSIInitiator_Session"
                                                  "Class")
        for initiator_session in initiator_sessions:
            devices = initiator_session.Devices
            for device in devices:
                device_number = device.DeviceNumber
                if device_number == drive_number:
                    return initiator_session.SessionId

    def get_device_number_for_target(self, target_iqn, target_lun):
        initiator_sessions = self._conn_wmi.query("SELECT * FROM "
                                                  "MSiSCSIInitiator_Session"
                                                  "Class WHERE TargetName='%s'"
                                                  % target_iqn)
        if not initiator_sessions:
            return None

        devices = initiator_sessions[0].Devices
        for device in devices:
            if device.ScsiLun == target_lun:
                return device.DeviceNumber

    def get_target_from_disk_path(self, disk_path):
        initiator_sessions = self._conn_wmi.MSiSCSIInitiator_SessionClass()
        drive_number = self._get_drive_number_from_disk_path(disk_path)
        if not drive_number:
            return None

        for initiator_session in initiator_sessions:
            devices = initiator_session.Devices
            for device in devices:
                if device.DeviceNumber == drive_number:
                    return (device.TargetName, device.ScsiLun)
