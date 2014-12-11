# Copyright 2014 Cloudbase Solutions Srl
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

from oslo_concurrency import processutils

from nova.i18n import _LE, _LW
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


def mount_share(mount_path, export_path,
                export_type, options=None):
    """Mount a remote export to mount_path.

    :param mount_path: place where the remote export will be mounted
    :param export_path: path of the export to be mounted
    :export_type: remote export type (e.g. cifs, nfs, etc.)
    :options: A list containing mount options
    """
    utils.execute('mkdir', '-p', mount_path)

    mount_cmd = ['mount', '-t', export_type]
    if options is not None:
        mount_cmd.extend(options)
    mount_cmd.extend([export_path, mount_path])

    try:
        utils.execute(*mount_cmd, run_as_root=True)
    except processutils.ProcessExecutionError as exc:
        if 'Device or resource busy' in exc.message:
            LOG.warn(_LW("%s is already mounted"), export_path)
        else:
            raise


def unmount_share(mount_path, export_path):
    """Unmount a remote share.

    :param mount_path: remote export mount point
    :param export_path: path of the remote export to be unmounted
    """
    try:
        utils.execute('umount', mount_path, run_as_root=True,
                      attempts=3, delay_on_retry=True)
    except processutils.ProcessExecutionError as exc:
        if 'target is busy' in exc.message:
            LOG.debug("The share %s is still in use.", export_path)
        else:
            LOG.exception(_LE("Couldn't unmount the share %s"),
                          export_path)
