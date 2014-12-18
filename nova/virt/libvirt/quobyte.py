# Copyright (c) 2015 Quobyte Inc.
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

import os

from oslo_concurrency import processutils

from nova import exception as nova_exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LI
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils


LOG = logging.getLogger(__name__)

SOURCE_PROTOCOL = 'quobyte'
SOURCE_TYPE = 'file'
DRIVER_CACHE = 'none'
DRIVER_IO = 'native'


def mount_volume(volume, mnt_base, configfile=None):
    """Wraps execute calls for mounting a Quobyte volume"""
    fileutils.ensure_tree(mnt_base)

    command = ['mount.quobyte', volume, mnt_base]
    if configfile:
        command.extend(['-c', configfile])

    LOG.debug('Mounting volume %s at mount point %s ...',
              volume,
              mnt_base)
    # Run mount command but do not fail on already mounted exit code
    utils.execute(*command, check_exit_code=[0, 4])
    LOG.info(_LI('Mounted volume: %s'), volume)


def umount_volume(mnt_base):
    """Wraps execute calls for unmouting a Quobyte volume"""
    try:
        utils.execute('umount.quobyte', mnt_base)
    except processutils.ProcessExecutionError as exc:
        if 'Device or resource busy' in exc.message:
            LOG.error(_LE("The Quobyte volume at %s is still in use."),
                      mnt_base)
        else:
            LOG.exception(_LE("Couldn't unmount the Quobyte Volume at %s"),
                          mnt_base)


def validate_volume(mnt_base):
    """Wraps execute calls for checking validity of a Quobyte volume"""
    command = ['getfattr', "-n", "quobyte.info", mnt_base]
    try:
        utils.execute(*command)
    except processutils.ProcessExecutionError as exc:
        msg = (_("The mount %(mount_path)s is not a valid"
                 " Quobyte volume. Error: %(exc)s")
               % {'mount_path': mnt_base, 'exc': exc})
        raise nova_exception.NovaException(msg)

    if not os.access(mnt_base, os.W_OK | os.X_OK):
        msg = (_LE("Volume is not writable. Please broaden the file"
                   " permissions. Mount: %s") % mnt_base)
        raise nova_exception.NovaException(msg)
