# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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
from oslo_log import log as logging

from nova import exception
from nova.i18n import _LW
from nova import utils
from nova.volume.encryptors import base


LOG = logging.getLogger(__name__)


class CryptsetupEncryptor(base.VolumeEncryptor):
    """A VolumeEncryptor based on dm-crypt.

    This VolumeEncryptor uses dm-crypt to encrypt the specified volume.
    """

    def __init__(self, connection_info, **kwargs):
        super(CryptsetupEncryptor, self).__init__(connection_info, **kwargs)

        # Fail if no device_path was set when connecting the volume, e.g. in
        # the case of libvirt network volume drivers.
        data = connection_info['data']
        if not data.get('device_path'):
            volume_id = data.get('volume_id') or connection_info.get('serial')
            raise exception.VolumeEncryptionNotSupported(
                volume_id=volume_id,
                volume_type=connection_info['driver_volume_type'])

        # the device's path as given to libvirt -- e.g., /dev/disk/by-path/...
        self.symlink_path = connection_info['data']['device_path']

        # a unique name for the volume -- e.g., the iSCSI participant name
        self.dev_name = 'crypt-%s' % self.symlink_path.split('/')[-1]

        # NOTE(tsekiyama): In older version of nova, dev_name was the same
        # as the symlink name. Now it has 'crypt-' prefix to avoid conflict
        # with multipath device symlink. To enable rolling update, we use the
        # old name when the encrypted volume already exists.
        old_dev_name = self.symlink_path.split('/')[-1]
        wwn = data.get('multipath_id')
        if self._is_crypt_device_available(old_dev_name):
            self.dev_name = old_dev_name
            LOG.debug("Using old encrypted volume name: %s", self.dev_name)
        elif wwn and wwn != old_dev_name:
            # FibreChannel device could be named '/dev/mapper/<WWN>'.
            if self._is_crypt_device_available(wwn):
                self.dev_name = wwn
                LOG.debug("Using encrypted volume name from wwn: %s",
                          self.dev_name)

        # the device's actual path on the compute host -- e.g., /dev/sd_
        self.dev_path = os.path.realpath(self.symlink_path)

    def _is_crypt_device_available(self, dev_name):
        if not os.path.exists('/dev/mapper/%s' % dev_name):
            return False

        try:
            utils.execute('cryptsetup', 'status', dev_name, run_as_root=True)
        except processutils.ProcessExecutionError as e:
            # If /dev/mapper/<dev_name> is a non-crypt block device (such as a
            # normal disk or multipath device), exit_code will be 1. In the
            # case, we will omit the warning message.
            if e.exit_code != 1:
                LOG.warning(_LW('cryptsetup status %(dev_name) exited '
                                'abnormally (status %(exit_code)s): %(err)s'),
                            {"dev_name": dev_name, "exit_code": e.exit_code,
                             "err": e.stderr})
            return False
        return True

    def _get_passphrase(self, key):
        """Convert raw key to string."""
        return ''.join(hex(x).replace('0x', '') for x in key)

    def _open_volume(self, passphrase, **kwargs):
        """Opens the LUKS partition on the volume using the specified
        passphrase.

        :param passphrase: the passphrase used to access the volume
        """
        LOG.debug("opening encrypted volume %s", self.dev_path)

        # NOTE(joel-coffman): cryptsetup will strip trailing newlines from
        # input specified on stdin unless --key-file=- is specified.
        cmd = ["cryptsetup", "create", "--key-file=-"]

        cipher = kwargs.get("cipher", None)
        if cipher is not None:
            cmd.extend(["--cipher", cipher])

        key_size = kwargs.get("key_size", None)
        if key_size is not None:
            cmd.extend(["--key-size", key_size])

        cmd.extend([self.dev_name, self.dev_path])

        utils.execute(*cmd, process_input=passphrase,
                      check_exit_code=True, run_as_root=True)

    def attach_volume(self, context, **kwargs):
        """Shadows the device and passes an unencrypted version to the
        instance.

        Transparent disk encryption is achieved by mounting the volume via
        dm-crypt and passing the resulting device to the instance. The
        instance is unaware of the underlying encryption due to modifying the
        original symbolic link to refer to the device mounted by dm-crypt.
        """

        key = self._get_key(context).get_encoded()
        passphrase = self._get_passphrase(key)

        self._open_volume(passphrase, **kwargs)

        # modify the original symbolic link to refer to the decrypted device
        utils.execute('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True)

    def _close_volume(self, **kwargs):
        """Closes the device (effectively removes the dm-crypt mapping)."""
        LOG.debug("closing encrypted volume %s", self.dev_path)
        # cryptsetup returns 4 when attempting to destroy a non-active
        # dm-crypt device. We are going to ignore this error code to make
        # nova deleting that instance successfully.
        utils.execute('cryptsetup', 'remove', self.dev_name,
                      run_as_root=True, check_exit_code=[0, 4])

    def detach_volume(self, **kwargs):
        """Removes the dm-crypt mapping for the device."""
        self._close_volume(**kwargs)
