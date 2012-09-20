# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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

import errno
import hashlib
import os

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.virt.libvirt import volume_nfs
from nova.volume import driver

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('nfs_shares_config',
                default=None,
                help='File with the list of available nfs shares'),
    cfg.StrOpt('nfs_disk_util',
               default='df',
               help='Use du or df for free space calculation'),
    cfg.BoolOpt('nfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.'))
]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_opts)
FLAGS.register_opts(volume_nfs.volume_opts)


class NfsDriver(driver.VolumeDriver):
    """NFS based volume driver. Creates file on NFS share for using it
    as block device on hypervisor."""

    def do_setup(self, context):
        """Any initialization the volume driver does while starting"""
        super(NfsDriver, self).do_setup(context)

        config = FLAGS.nfs_shares_config
        if not config:
            LOG.warn(_("There's no NFS config file configured "))
        if not config or not os.path.exists(config):
            msg = _("NFS config file doesn't exist")
            LOG.warn(msg)
            raise exception.NfsException(msg)

        try:
            self._execute('mount.nfs', check_exit_code=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.NfsException('mount.nfs is not installed')
            else:
                raise

    def check_for_setup_error(self):
        """Just to override parent behavior"""
        pass

    def create_volume(self, volume):
        """Creates a volume"""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume['provider_location']:
            LOG.warn(_('Volume %s does not have provider_location specified, '
                     'skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        mounted_path = self.local_path(volume)

        if not self._path_exists(mounted_path):
            volume = volume['name']

            LOG.warn(_('Trying to delete non-existing volume %(volume)s at '
                     'path %(mounted_path)s') % locals())
            return

        self._execute('rm', '-f', mounted_path, run_as_root=True)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""
        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume):
        """Exports the volume. Can optionally return a Dictionary of changes
        to the volume object to be persisted."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        data = {'export': volume['provider_location'],
                'name': volume['name']}
        return {
            'driver_volume_type': 'nfs',
            'data': data
        }

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector"""
        pass

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume
        :param volume: volume reference
        """
        nfs_share = volume['provider_location']
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume['name'])

    def _create_sparsed_file(self, path, size):
        """Creates file with 0 disk usage"""
        self._execute('truncate', '-s', self._sizestr(size),
                      path, run_as_root=True)

    def _create_regular_file(self, path, size):
        """Creates regular file of given size. Takes a lot of time for large
        files"""
        KB = 1024
        MB = KB * 1024
        GB = MB * 1024

        block_size_mb = 1
        block_count = size * GB / (block_size_mb * MB)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=True)

    def _set_rw_permissions_for_all(self, path):
        """Sets 666 permissions for the path"""
        self._execute('chmod', 'ugo+rw', path, run_as_root=True)

    def _do_create_volume(self, volume):
        """Create a volume on given nfs_share
        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        if FLAGS.nfs_sparsed_volumes:
            self._create_sparsed_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _ensure_shares_mounted(self):
        """Look for NFS shares in the flags and tries to mount them locally"""
        self._mounted_shares = []

        for share in self._load_shares_config():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception, exc:
                LOG.warning('Exception during mounting %s' % (exc,))

        LOG.debug('Available shares %s' % str(self._mounted_shares))

    def _load_shares_config(self):
        return [share.strip() for share in open(FLAGS.nfs_shares_config)
                if share and not share.startswith('#')]

    def _ensure_share_mounted(self, nfs_share):
        """Mount NFS share
        :param nfs_share:
        """
        mount_path = self._get_mount_point_for_share(nfs_share)
        self._mount_nfs(nfs_share, mount_path, ensure=True)

    def _find_share(self, volume_size_for):
        """Choose NFS share among available ones for given volume size. Current
        implementation looks for greatest capacity
        :param volume_size_for: int size in Gb
        """

        if not self._mounted_shares:
            raise exception.NfsNoSharesMounted()

        greatest_size = 0
        greatest_share = None

        for nfs_share in self._mounted_shares:
            capacity = self._get_available_capacity(nfs_share)
            if capacity > greatest_size:
                greatest_share = nfs_share
                greatest_size = capacity

        if volume_size_for * 1024 * 1024 * 1024 > greatest_size:
            raise exception.NfsNoSuitableShareFound(
                    volume_size=volume_size_for)
        return greatest_share

    def _get_mount_point_for_share(self, nfs_share):
        """
        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        return os.path.join(FLAGS.nfs_mount_point_base,
                            self._get_hash_str(nfs_share))

    def _get_available_capacity(self, nfs_share):
        """Calculate available space on the NFS share
        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        mount_point = self._get_mount_point_for_share(nfs_share)

        out, _ = self._execute('df', '-P', '-B', '1', mount_point,
                               run_as_root=True)
        out = out.splitlines()[1]

        available = 0

        if FLAGS.nfs_disk_util == 'df':
            available = int(out.split()[3])
        else:
            size = int(out.split()[1])
            out, _ = self._execute('du', '-sb', '--apparent-size',
                                   '--exclude', '*snapshot*', mount_point,
                                   run_as_root=True)
            used = int(out.split()[0])
            available = size - used

        return available

    def _mount_nfs(self, nfs_share, mount_path, ensure=False):
        """Mount NFS share to mount path"""
        if not self._path_exists(mount_path):
            self._execute('mkdir', '-p', mount_path)

        try:
            self._execute('mount', '-t', 'nfs', nfs_share, mount_path,
                          run_as_root=True)
        except exception.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.stderr:
                LOG.warn(_("%s is already mounted"), nfs_share)
            else:
                raise

    def _path_exists(self, path):
        """Check given path """
        try:
            self._execute('stat', path, run_as_root=True)
            return True
        except exception.ProcessExecutionError as exc:
            if 'No such file or directory' in exc.stderr:
                return False
            else:
                raise

    def _get_hash_str(self, base_str):
        """returns string that represents hash of base_str (in a hex format)"""
        return hashlib.md5(base_str).hexdigest()
