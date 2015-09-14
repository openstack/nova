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


from oslo_concurrency import processutils
from oslo_log import log as logging

from nova.i18n import _LI
from nova.i18n import _LW
from nova import utils
from nova.volume.encryptors import cryptsetup


LOG = logging.getLogger(__name__)


def is_luks(device):
    """Checks if the specified device uses LUKS for encryption.

    :param device: the device to check
    :returns: true if the specified device uses LUKS; false otherwise
    """
    try:
        # check to see if the device uses LUKS: exit status is 0
        # if the device is a LUKS partition and non-zero if not
        utils.execute('cryptsetup', 'isLuks', '--verbose', device,
                      run_as_root=True, check_exit_code=True)
        return True
    except processutils.ProcessExecutionError as e:
        LOG.warning(_LW("isLuks exited abnormally (status %(exit_code)s): "
                        "%(stderr)s"),
                    {"exit_code": e.exit_code, "stderr": e.stderr})
        return False


class LuksEncryptor(cryptsetup.CryptsetupEncryptor):
    """A VolumeEncryptor based on LUKS.

    This VolumeEncryptor uses dm-crypt to encrypt the specified volume.
    """
    def __init__(self, connection_info, **kwargs):
        super(LuksEncryptor, self).__init__(connection_info, **kwargs)

    def _format_volume(self, passphrase, **kwargs):
        """Creates a LUKS header on the volume.

        :param passphrase: the passphrase used to access the volume
        """
        LOG.debug("formatting encrypted volume %s", self.dev_path)

        # NOTE(joel-coffman): cryptsetup will strip trailing newlines from
        # input specified on stdin unless --key-file=- is specified.
        cmd = ["cryptsetup", "--batch-mode", "luksFormat", "--key-file=-"]

        cipher = kwargs.get("cipher", None)
        if cipher is not None:
            cmd.extend(["--cipher", cipher])

        key_size = kwargs.get("key_size", None)
        if key_size is not None:
            cmd.extend(["--key-size", key_size])

        cmd.extend([self.dev_path])

        utils.execute(*cmd, process_input=passphrase,
                      check_exit_code=True, run_as_root=True, attempts=3)

    def _open_volume(self, passphrase, **kwargs):
        """Opens the LUKS partition on the volume using the specified
        passphrase.

        :param passphrase: the passphrase used to access the volume
        """
        LOG.debug("opening encrypted volume %s", self.dev_path)
        utils.execute('cryptsetup', 'luksOpen', '--key-file=-',
                      self.dev_path, self.dev_name, process_input=passphrase,
                      run_as_root=True, check_exit_code=True)

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

        try:
            self._open_volume(passphrase, **kwargs)
        except processutils.ProcessExecutionError as e:
            if e.exit_code == 1 and not is_luks(self.dev_path):
                # the device has never been formatted; format it and try again
                LOG.info(_LI("%s is not a valid LUKS device;"
                             " formatting device for first use"),
                         self.dev_path)
                self._format_volume(passphrase, **kwargs)
                self._open_volume(passphrase, **kwargs)
            else:
                raise

        # modify the original symbolic link to refer to the decrypted device
        utils.execute('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True)

    def _close_volume(self, **kwargs):
        """Closes the device (effectively removes the dm-crypt mapping)."""
        LOG.debug("closing encrypted volume %s", self.dev_path)
        utils.execute('cryptsetup', 'luksClose', self.dev_name,
                      run_as_root=True, check_exit_code=True,
                      attempts=3)
