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

import abc
import functools
import os
import tempfile

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
import six

from nova.i18n import _LE, _LW
from nova import utils

LOG = logging.getLogger(__name__)

libvirt_opts = [
    cfg.StrOpt('remote_filesystem_transport',
               default='ssh',
               choices=('ssh', 'rsync'),
               help='Use ssh or rsync transport for creating, copying, '
                    'removing files on the remote host.'),
    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts, 'libvirt')


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
        if 'Device or resource busy' in six.text_type(exc):
            LOG.warning(_LW("%s is already mounted"), export_path)
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
        if 'target is busy' in six.text_type(exc):
            LOG.debug("The share %s is still in use.", export_path)
        else:
            LOG.exception(_LE("Couldn't unmount the share %s"),
                          export_path)


class RemoteFilesystem(object):
    """Represents actions that can be taken on a remote host's filesystem."""

    def __init__(self):
        transport = CONF.libvirt.remote_filesystem_transport
        cls_name = '.'.join([__name__, transport.capitalize()])
        cls_name += 'Driver'
        self.driver = importutils.import_object(cls_name)

    def create_file(self, host, dst_path, on_execute=None,
                    on_completion=None):
        LOG.debug("Creating file %s on remote host %s", dst_path, host)
        self.driver.create_file(host, dst_path, on_execute=on_execute,
                                on_completion=on_completion)

    def remove_file(self, host, dst_path, on_execute=None,
                    on_completion=None):
        LOG.debug("Removing file %s on remote host %s", dst_path, host)
        self.driver.remove_file(host, dst_path, on_execute=on_execute,
                                on_completion=on_completion)

    def create_dir(self, host, dst_path, on_execute=None,
                    on_completion=None):
        LOG.debug("Creating directory %s on remote host %s", dst_path, host)
        self.driver.create_dir(host, dst_path, on_execute=on_execute,
                               on_completion=on_completion)

    def remove_dir(self, host, dst_path, on_execute=None,
                    on_completion=None):
        LOG.debug("Removing directory %s on remote host %s", dst_path, host)
        self.driver.remove_dir(host, dst_path, on_execute=on_execute,
                               on_completion=on_completion)

    def copy_file(self, src, dst, on_execute=None,
                    on_completion=None, compression=True):
        LOG.debug("Copying file %s to %s", src, dst)
        self.driver.copy_file(src, dst, on_execute=on_execute,
                              on_completion=on_completion,
                              compression=compression)


@six.add_metaclass(abc.ABCMeta)
class RemoteFilesystemDriver(object):
    @abc.abstractmethod
    def create_file(self, host, dst_path, on_execute, on_completion):
        """Create file on the remote system.

        :param host: Remote host
        :param dst_path: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """

    @abc.abstractmethod
    def remove_file(self, host, dst_path, on_execute, on_completion):
        """Removes a file on a remote host.

        :param host: Remote host
        :param dst_path: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """

    @abc.abstractmethod
    def create_dir(self, host, dst_path, on_execute, on_completion):
        """Create directory on the remote system.

        :param host: Remote host
        :param dst_path: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """

    @abc.abstractmethod
    def remove_dir(self, host, dst_path, on_execute, on_completion):
        """Removes a directory on a remote host.

        :param host: Remote host
        :param dst_path: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """

    @abc.abstractmethod
    def copy_file(self, src, dst, on_execute, on_completion):
        """Copy file to/from remote host.

        Remote address must be specified in format:
            REM_HOST_IP_ADDRESS:REM_HOST_PATH
        For example:
            192.168.1.10:/home/file

        :param src: Source address
        :param dst: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
        """


class SshDriver(RemoteFilesystemDriver):

    def create_file(self, host, dst_path, on_execute, on_completion):
        utils.execute('ssh', host, 'touch', dst_path,
                      on_execute=on_execute, on_completion=on_completion)

    def remove_file(self, host, dst, on_execute, on_completion):
        utils.execute('ssh', host, 'rm', dst,
                      on_execute=on_execute, on_completion=on_completion)

    def create_dir(self, host, dst_path, on_execute, on_completion):
        utils.execute('ssh', host, 'mkdir', '-p', dst_path,
                      on_execute=on_execute, on_completion=on_completion)

    def remove_dir(self, host, dst, on_execute, on_completion):
        utils.execute('ssh', host, 'rm', '-rf', dst,
                      on_execute=on_execute, on_completion=on_completion)

    def copy_file(self, src, dst, on_execute, on_completion, compression):
        utils.execute('scp', src, dst,
                      on_execute=on_execute, on_completion=on_completion)


def create_tmp_dir(function):
    """Creates temporary directory for rsync purposes.
    Removes created directory in the end.
    """

    @functools.wraps(function)
    def decorated_function(*args, **kwargs):
        # Create directory
        tmp_dir_path = tempfile.mkdtemp()
        kwargs['tmp_dir_path'] = tmp_dir_path

        try:
            return function(*args, **kwargs)
        finally:
            # Remove directory
            utils.execute('rm', '-rf', tmp_dir_path)

    return decorated_function


class RsyncDriver(RemoteFilesystemDriver):

    @create_tmp_dir
    def create_file(self, host, dst_path, on_execute, on_completion, **kwargs):
        dir_path = os.path.dirname(os.path.normpath(dst_path))

        # Create target dir inside temporary directory
        local_tmp_dir = os.path.join(kwargs['tmp_dir_path'],
                                     dir_path.strip(os.path.sep))
        utils.execute('mkdir', '-p', local_tmp_dir,
                      on_execute=on_execute, on_completion=on_completion)

        # Create file in directory
        file_name = os.path.basename(os.path.normpath(dst_path))
        local_tmp_file = os.path.join(local_tmp_dir, file_name)
        utils.execute('touch', local_tmp_file,
                      on_execute=on_execute, on_completion=on_completion)
        RsyncDriver._synchronize_object(kwargs['tmp_dir_path'],
                                        host, dst_path,
                                        on_execute=on_execute,
                                        on_completion=on_completion)

    @create_tmp_dir
    def remove_file(self, host, dst, on_execute, on_completion, **kwargs):
        # Delete file
        RsyncDriver._remove_object(kwargs['tmp_dir_path'], host, dst,
                                   on_execute=on_execute,
                                   on_completion=on_completion)

    @create_tmp_dir
    def create_dir(self, host, dst_path, on_execute, on_completion, **kwargs):
        dir_path = os.path.normpath(dst_path)

        # Create target dir inside temporary directory
        local_tmp_dir = os.path.join(kwargs['tmp_dir_path'],
                                 dir_path.strip(os.path.sep))
        utils.execute('mkdir', '-p', local_tmp_dir,
                      on_execute=on_execute, on_completion=on_completion)
        RsyncDriver._synchronize_object(kwargs['tmp_dir_path'],
                                        host, dst_path,
                                        on_execute=on_execute,
                                        on_completion=on_completion)

    @create_tmp_dir
    def remove_dir(self, host, dst, on_execute, on_completion, **kwargs):
        # Remove remote directory's content
        utils.execute('rsync', '--archive', '--delete-excluded',
                      kwargs['tmp_dir_path'] + os.path.sep,
                      '%s:%s' % (host, dst),
                      on_execute=on_execute, on_completion=on_completion)

        # Delete empty directory
        RsyncDriver._remove_object(kwargs['tmp_dir_path'], host, dst,
                                   on_execute=on_execute,
                                   on_completion=on_completion)

    @staticmethod
    def _remove_object(src, host, dst, on_execute, on_completion):
        """Removes a file or empty directory on a remote host.

        :param src: Empty directory used for rsync purposes
        :param host: Remote host
        :param dst: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """
        utils.execute('rsync', '--archive', '--delete',
                      '--include', os.path.basename(os.path.normpath(dst)),
                      '--exclude', '*',
                      os.path.normpath(src) + os.path.sep,
                      '%s:%s' % (host, os.path.dirname(os.path.normpath(dst))),
                      on_execute=on_execute, on_completion=on_completion)

    @staticmethod
    def _synchronize_object(src, host, dst, on_execute, on_completion):
        """Creates a file or empty directory on a remote host.

        :param src: Empty directory used for rsync purposes
        :param host: Remote host
        :param dst: Destination path
        :param on_execute: Callback method to store pid of process in cache
        :param on_completion: Callback method to remove pid of process from
                              cache
        """

        # For creating path on the remote host rsync --relative path must
        # be used. With a modern rsync on the sending side (beginning with
        # 2.6.7), you can insert a dot and a slash into the source path,
        # like this:
        #   rsync -avR /foo/./bar/baz.c remote:/tmp/
        # That would create /tmp/bar/baz.c on the remote machine.
        # (Note that the dot must be followed by a slash, so "/foo/."
        # would not be abbreviated.)
        relative_tmp_file_path = os.path.join(
            src, './',
            os.path.normpath(dst).strip(os.path.sep))

        # Do relative rsync local directory with remote root directory
        utils.execute('rsync', '--archive', '--relative', '--no-implied-dirs',
                      relative_tmp_file_path, '%s:%s' % (host, os.path.sep),
                      on_execute=on_execute, on_completion=on_completion)

    def copy_file(self, src, dst, on_execute, on_completion, compression):
        args = ['rsync', '--sparse', src, dst]
        if compression:
            args.append('--compress')
        utils.execute(*args,
                      on_execute=on_execute, on_completion=on_completion)
