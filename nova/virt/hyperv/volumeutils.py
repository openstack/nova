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

Official Microsoft iSCSI Initiator and iSCSI command line interface
documentation can be retrieved at:
http://www.microsoft.com/en-us/download/details.aspx?id=34750
"""

import re
import time

from oslo.config import cfg

from nova.i18n import _
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.hyperv import basevolumeutils
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class VolumeUtils(basevolumeutils.BaseVolumeUtils):

    def __init__(self):
        super(VolumeUtils, self).__init__()

    def execute(self, *args, **kwargs):
        stdout_value, stderr_value = utils.execute(*args, **kwargs)
        if stdout_value.find('The operation completed successfully') == -1:
            raise vmutils.HyperVException(_('An error has occurred when '
                                            'calling the iscsi initiator: %s')
                                          % stdout_value)
        return stdout_value

    def _login_target_portal(self, target_portal):
        (target_address,
         target_port) = utils.parse_server_string(target_portal)

        output = self.execute('iscsicli.exe', 'ListTargetPortals')
        pattern = r'Address and Socket *: (.*)'
        portals = [addr.split() for addr in re.findall(pattern, output)]
        LOG.debug("Ensuring connection to portal: %s" % target_portal)
        if [target_address, str(target_port)] in portals:
            self.execute('iscsicli.exe', 'RefreshTargetPortal',
                         target_address, target_port)
        else:
            # Adding target portal to iscsi initiator. Sending targets
            self.execute('iscsicli.exe', 'AddTargetPortal',
                         target_address, target_port,
                         '*', '*', '*', '*', '*', '*', '*', '*', '*', '*', '*',
                         '*', '*')

    def login_storage_target(self, target_lun, target_iqn, target_portal,
                             auth_username=None, auth_password=None):
        """Ensure that the target is logged in."""

        self._login_target_portal(target_portal)
        # Listing targets
        self.execute('iscsicli.exe', 'ListTargets')

        retry_count = CONF.hyperv.volume_attach_retry_count

        # If the target is not connected, at least two iterations are needed:
        # one for performing the login and another one for checking if the
        # target was logged in successfully.
        if retry_count < 2:
            retry_count = 2

        for attempt in xrange(retry_count):
            try:
                session_info = self.execute('iscsicli.exe', 'SessionList')
                if session_info.find(target_iqn) == -1:
                    # Sending login
                    self.execute('iscsicli.exe', 'qlogintarget', target_iqn,
                                 auth_username, auth_password)
                else:
                    return
            except vmutils.HyperVException as exc:
                LOG.debug("Attempt %(attempt)d to connect to target  "
                          "%(target_iqn)s failed. Retrying. "
                          "Exceptipn: %(exc)s ",
                          {'target_iqn': target_iqn,
                           'exc': exc,
                           'attempt': attempt})
                time.sleep(CONF.hyperv.volume_attach_retry_interval)

        raise vmutils.HyperVException(_('Failed to login target %s') %
                                      target_iqn)

    def logout_storage_target(self, target_iqn):
        """Logs out storage target through its session id."""

        sessions = self._conn_wmi.query("SELECT * FROM "
                                        "MSiSCSIInitiator_SessionClass "
                                        "WHERE TargetName='%s'" % target_iqn)
        for session in sessions:
            self.execute_log_out(session.SessionId)

    def execute_log_out(self, session_id):
        """Executes log out of the session described by its session ID."""
        self.execute('iscsicli.exe', 'logouttarget', session_id)
