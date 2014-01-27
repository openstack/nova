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
Helper methods for operations related to the management of volumes
and storage repositories on Windows Server 2012 and above
"""
import sys
import time

if sys.platform == 'win32':
    import wmi

from oslo.config import cfg

from nova import utils
from nova.virt.hyperv import basevolumeutils

CONF = cfg.CONF


class VolumeUtilsV2(basevolumeutils.BaseVolumeUtils):
    def __init__(self, host='.'):
        super(VolumeUtilsV2, self).__init__(host)

        storage_namespace = '//%s/root/microsoft/windows/storage' % host
        if sys.platform == 'win32':
            self._conn_storage = wmi.WMI(moniker=storage_namespace)

    def login_storage_target(self, target_lun, target_iqn, target_portal):
        """Add target portal, list targets and logins to the target."""
        (target_address,
         target_port) = utils.parse_server_string(target_portal)

        #Adding target portal to iscsi initiator. Sending targets
        portal = self._conn_storage.MSFT_iSCSITargetPortal
        portal.New(TargetPortalAddress=target_address,
                   TargetPortalPortNumber=target_port)
        #Connecting to the target
        target = self._conn_storage.MSFT_iSCSITarget
        target.Connect(NodeAddress=target_iqn,
                       IsPersistent=True)
        #Waiting the disk to be mounted.
        #TODO(pnavarro): Check for the operation to end instead of
        #relying on a timeout
        time.sleep(CONF.hyperv.volume_attach_retry_interval)

    def logout_storage_target(self, target_iqn):
        """Logs out storage target through its session id."""
        targets = self._conn_storage.MSFT_iSCSITarget(NodeAddress=target_iqn)
        if targets:
            target = targets[0]
            if target.IsConnected:
                sessions = self._conn_storage.MSFT_iSCSISession(
                    TargetNodeAddress=target_iqn)

                for session in sessions:
                    if session.IsPersistent:
                        session.Unregister()

                target.Disconnect()

    def execute_log_out(self, session_id):
        sessions = self._conn_wmi.MSiSCSIInitiator_SessionClass(
            SessionId=session_id)
        if sessions:
            self.logout_storage_target(sessions[0].TargetName)
