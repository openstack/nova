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

import sys

from nova import block_device
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.virt import driver

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import _winreg

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.config')


class BaseVolumeUtils(object):

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
            'ip': CONF.my_ip,
            'initiator': initiator_name,
        }

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
