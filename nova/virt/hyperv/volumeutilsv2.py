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

from nova.i18n import _
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.hyperv import basevolumeutils
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class VolumeUtilsV2(basevolumeutils.BaseVolumeUtils):
    _CHAP_AUTH_TYPE = 'ONEWAYCHAP'

    def __init__(self, host='.'):
        super(VolumeUtilsV2, self).__init__(host)

        storage_namespace = '//%s/root/microsoft/windows/storage' % host
        if sys.platform == 'win32':
            self._conn_storage = wmi.WMI(moniker=storage_namespace)

    def _login_target_portal(self, target_portal):
        (target_address,
         target_port) = utils.parse_server_string(target_portal)

        # Checking if the portal is already connected.
        portal = self._conn_storage.query("SELECT * FROM "
                                          "MSFT_iSCSITargetPortal "
                                          "WHERE TargetPortalAddress='%s' "
                                          "AND TargetPortalPortNumber='%s'"
                                          % (target_address, target_port))
        if portal:
            portal[0].Update()
        else:
            # Adding target portal to iscsi initiator. Sending targets
            portal = self._conn_storage.MSFT_iSCSITargetPortal
            portal.New(TargetPortalAddress=target_address,
                       TargetPortalPortNumber=target_port)

    def login_storage_target(self, target_lun, target_iqn, target_portal,
                             auth_username=None, auth_password=None):
        """Ensure that the target is logged in."""

        self._login_target_portal(target_portal)

        retry_count = CONF.hyperv.volume_attach_retry_count

        # If the target is not connected, at least two iterations are needed:
        # one for performing the login and another one for checking if the
        # target was logged in successfully.
        if retry_count < 2:
            retry_count = 2

        for attempt in xrange(retry_count):
            target = self._conn_storage.query("SELECT * FROM MSFT_iSCSITarget "
                                              "WHERE NodeAddress='%s' " %
                                              target_iqn)

            if target and target[0].IsConnected:
                if attempt == 0:
                    # The target was already connected but an update may be
                    # required
                    target[0].Update()
                return
            try:
                target = self._conn_storage.MSFT_iSCSITarget
                auth = {}
                if auth_username and auth_password:
                    auth['AuthenticationType'] = self._CHAP_AUTH_TYPE
                    auth['ChapUsername'] = auth_username
                    auth['ChapSecret'] = auth_password
                target.Connect(NodeAddress=target_iqn,
                               IsPersistent=True, **auth)
                time.sleep(CONF.hyperv.volume_attach_retry_interval)
            except wmi.x_wmi as exc:
                LOG.debug("Attempt %(attempt)d to connect to target  "
                          "%(target_iqn)s failed. Retrying. "
                          "WMI exception: %(exc)s " %
                          {'target_iqn': target_iqn,
                           'exc': exc,
                           'attempt': attempt})
        raise vmutils.HyperVException(_('Failed to login target %s') %
                                      target_iqn)

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
