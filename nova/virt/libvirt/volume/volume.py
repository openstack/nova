# Copyright 2011 OpenStack Foundation
# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Volume drivers for libvirt."""

import os
import re

from os_brick.initiator import connector
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
import six

from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LW
from nova import paths
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import remotefs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume'),
    cfg.IntOpt('num_iser_scan_tries',
               default=5,
               help='Number of times to rescan iSER target to find volume'),
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt UUID of the secret for the rbd_user'
                    'volumes'),
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the NFS volume is mounted on the'
               ' compute node'),
    cfg.StrOpt('nfs_mount_options',
               help='Mount options passed to the NFS client. See section '
                    'of the nfs man page for details'),
    cfg.StrOpt('smbfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the SMBFS shares are mounted on the '
                    'compute node'),
    cfg.StrOpt('smbfs_mount_options',
               default='',
               help='Mount options passed to the SMBFS client. See '
                    'mount.cifs man page for details. Note that the '
                    'libvirt-qemu uid and gid must be specified.'),
    cfg.IntOpt('num_aoe_discover_tries',
               default=3,
               help='Number of times to rediscover AoE target to find volume'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the glusterfs volume is mounted on the '
                    'compute node'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI volume'),
    cfg.BoolOpt('iser_use_multipath',
                default=False,
                help='Use multipath connection of the iSER volume'),
    cfg.ListOpt('qemu_allowed_storage_drivers',
                default=[],
                help='Protocols listed here will be accessed directly '
                     'from QEMU. Currently supported protocols: [gluster]'),
    cfg.StrOpt('iscsi_iface',
               deprecated_name='iscsi_transport',
               help='The iSCSI transport iface to use to connect to target in '
                    'case offload support is desired. Default format is of '
                    'the form <transport_name>.<hwaddress> where '
                    '<transport_name> is one of (be2iscsi, bnx2i, cxgb3i, '
                    'cxgb4i, qla4xxx, ocs) and <hwadress> is the MAC address '
                    'of the interface and can be generated via the '
                    'iscsiadm -m iface command. Do not confuse the '
                    'iscsi_iface parameter to be provided here with the '
                    'actual transport name.'),
                    # iser is also supported, but use LibvirtISERVolumeDriver
                    # instead
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class LibvirtBaseVolumeDriver(object):
    """Base class for volume drivers."""
    def __init__(self, connection, is_block_dev):
        self.connection = connection
        self.is_block_dev = is_block_dev

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = vconfig.LibvirtConfigGuestDisk()
        conf.driver_name = libvirt_utils.pick_disk_driver_name(
            self.connection._host.get_version(),
            self.is_block_dev
        )

        conf.source_device = disk_info['type']
        conf.driver_format = "raw"
        conf.driver_cache = "none"
        conf.target_dev = disk_info['dev']
        conf.target_bus = disk_info['bus']
        conf.serial = connection_info.get('serial')

        # Support for block size tuning
        data = {}
        if 'data' in connection_info:
            data = connection_info['data']
        if 'logical_block_size' in data:
            conf.logical_block_size = data['logical_block_size']
        if 'physical_block_size' in data:
            conf.physical_block_size = data['physical_block_size']

        # Extract rate_limit control parameters
        if 'qos_specs' in data and data['qos_specs']:
            tune_opts = ['total_bytes_sec', 'read_bytes_sec',
                         'write_bytes_sec', 'total_iops_sec',
                         'read_iops_sec', 'write_iops_sec']
            specs = data['qos_specs']
            if isinstance(specs, dict):
                for k, v in six.iteritems(specs):
                    if k in tune_opts:
                        new_key = 'disk_' + k
                        setattr(conf, new_key, v)
            else:
                LOG.warn(_LW('Unknown content in connection_info/'
                             'qos_specs: %s'), specs)

        # Extract access_mode control parameters
        if 'access_mode' in data and data['access_mode']:
            access_mode = data['access_mode']
            if access_mode in ('ro', 'rw'):
                conf.readonly = access_mode == 'ro'
            else:
                LOG.error(_LE('Unknown content in '
                              'connection_info/access_mode: %s'),
                          access_mode)
                raise exception.InvalidVolumeAccessMode(
                    access_mode=access_mode)

        return conf

    def _get_secret_uuid(self, conf, password=None):
        secret = self.connection._host.find_secret(conf.source_protocol,
                                                   conf.source_name)
        if secret is None:
            secret = self.connection._host.create_secret(conf.source_protocol,
                                                         conf.source_name,
                                                         password)
        return secret.UUIDString()

    def _delete_secret_by_name(self, connection_info):
        source_protocol = connection_info['driver_volume_type']
        netdisk_properties = connection_info['data']
        if source_protocol == 'rbd':
            return
        elif source_protocol == 'iscsi':
            usage_type = 'iscsi'
            usage_name = ("%(target_iqn)s/%(target_lun)s" %
                          netdisk_properties)
            self.connection._host.delete_secret(usage_type, usage_name)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""
        pass

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""
        pass


class LibvirtVolumeDriver(LibvirtBaseVolumeDriver):
    """Class for volumes backed by local file."""
    def __init__(self, connection):
        super(LibvirtVolumeDriver,
              self).__init__(connection, is_block_dev=True)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtVolumeDriver,
                     self).get_config(connection_info, disk_info)
        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        return conf


class LibvirtFakeVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach fake volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtFakeVolumeDriver,
              self).__init__(connection, is_block_dev=True)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtFakeVolumeDriver,
                     self).get_config(connection_info, disk_info)
        conf.source_type = "network"
        conf.source_protocol = "fake"
        conf.source_name = "fake"
        return conf


class LibvirtNetVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtNetVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtNetVolumeDriver,
                     self).get_config(connection_info, disk_info)

        netdisk_properties = connection_info['data']
        conf.source_type = "network"
        conf.source_protocol = connection_info['driver_volume_type']
        conf.source_name = netdisk_properties.get('name')
        conf.source_hosts = netdisk_properties.get('hosts', [])
        conf.source_ports = netdisk_properties.get('ports', [])
        auth_enabled = netdisk_properties.get('auth_enabled')
        if (conf.source_protocol == 'rbd' and
                CONF.libvirt.rbd_secret_uuid):
            conf.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
            auth_enabled = True  # Force authentication locally
            if CONF.libvirt.rbd_user:
                conf.auth_username = CONF.libvirt.rbd_user
        if conf.source_protocol == 'iscsi':
            try:
                conf.source_name = ("%(target_iqn)s/%(target_lun)s" %
                                    netdisk_properties)
                target_portal = netdisk_properties['target_portal']
            except KeyError:
                raise exception.NovaException(_("Invalid volume source data"))

            ip, port = utils.parse_server_string(target_portal)
            if ip == '' or port == '':
                raise exception.NovaException(_("Invalid target_lun"))
            conf.source_hosts = [ip]
            conf.source_ports = [port]
            if netdisk_properties.get('auth_method') == 'CHAP':
                auth_enabled = True
                conf.auth_secret_type = 'iscsi'
                password = netdisk_properties.get('auth_password')
                conf.auth_secret_uuid = self._get_secret_uuid(conf, password)
        if auth_enabled:
            conf.auth_username = (conf.auth_username or
                                  netdisk_properties['auth_username'])
            conf.auth_secret_type = (conf.auth_secret_type or
                                     netdisk_properties['secret_type'])
            conf.auth_secret_uuid = (conf.auth_secret_uuid or
                                     netdisk_properties['secret_uuid'])
        return conf

    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""
        super(LibvirtNetVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)
        self._delete_secret_by_name(connection_info)


class LibvirtISCSIVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def __init__(self, connection):
        super(LibvirtISCSIVolumeDriver, self).__init__(connection,
                                                       is_block_dev=True)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            'ISCSI', utils._get_root_helper(),
            use_multipath=CONF.libvirt.iscsi_use_multipath,
            device_scan_attempts=CONF.libvirt.num_iscsi_scan_tries,
            transport=self._get_transport())

    def _get_transport(self):
        if CONF.libvirt.iscsi_iface:
            transport = CONF.libvirt.iscsi_iface
        else:
            transport = 'default'

        return transport

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtISCSIVolumeDriver,
                     self).get_config(connection_info, disk_info)
        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        return conf

    def connect_volume(self, connection_info, disk_info):
        """Attach the volume to instance_name."""

        LOG.debug("Calling os-brick to attach iSCSI Volume")
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached iSCSI volume %s", device_info)

        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""

        LOG.debug("calling os-brick to detach iSCSI Volume")
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected iSCSI Volume %s", disk_dev)

        super(LibvirtISCSIVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)


class LibvirtISERVolumeDriver(LibvirtISCSIVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def __init__(self, connection):
        super(LibvirtISERVolumeDriver, self).__init__(connection)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            'ISER', utils._get_root_helper(),
            use_multipath=CONF.libvirt.iser_use_multipath,
            device_scan_attempts=CONF.libvirt.num_iser_scan_tries,
            transport=self._get_transport())

    def _get_transport(self):
        return 'iser'


class LibvirtNFSVolumeDriver(LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for NFS."""

    def __init__(self, connection):
        """Create back-end to nfs."""
        super(LibvirtNFSVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def _get_device_path(self, connection_info):
        path = os.path.join(CONF.libvirt.nfs_mount_point_base,
            utils.get_hash_str(connection_info['data']['export']))
        path = os.path.join(path, connection_info['data']['name'])
        return path

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtNFSVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""
        options = connection_info['data'].get('options')
        self._ensure_mounted(connection_info['data']['export'], options)

        connection_info['data']['device_path'] = \
            self._get_device_path(connection_info)

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""

        export = connection_info['data']['export']
        mount_path = os.path.join(CONF.libvirt.nfs_mount_point_base,
                                  utils.get_hash_str(export))

        try:
            utils.execute('umount', mount_path, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ('device is busy' in exc.message or
                'target is busy' in exc.message):
                LOG.debug("The NFS share %s is still in use.", export)
            else:
                LOG.exception(_LE("Couldn't unmount the NFS share %s"), export)

    def _ensure_mounted(self, nfs_export, options=None):
        """@type nfs_export: string
           @type options: string
        """
        mount_path = os.path.join(CONF.libvirt.nfs_mount_point_base,
                                  utils.get_hash_str(nfs_export))
        if not libvirt_utils.is_mounted(mount_path, nfs_export):
            self._mount_nfs(mount_path, nfs_export, options, ensure=True)
        return mount_path

    def _mount_nfs(self, mount_path, nfs_share, options=None, ensure=False):
        """Mount nfs export to mount path."""
        utils.execute('mkdir', '-p', mount_path)

        # Construct the NFS mount command.
        nfs_cmd = ['mount', '-t', 'nfs']
        if CONF.libvirt.nfs_mount_options is not None:
            nfs_cmd.extend(['-o', CONF.libvirt.nfs_mount_options])
        if options:
            nfs_cmd.extend(options.split(' '))
        nfs_cmd.extend([nfs_share, mount_path])

        try:
            utils.execute(*nfs_cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.message:
                LOG.warn(_LW("%s is already mounted"), nfs_share)
            else:
                raise


class LibvirtSMBFSVolumeDriver(LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for SMBFS."""

    def __init__(self, connection):
        super(LibvirtSMBFSVolumeDriver,
              self).__init__(connection, is_block_dev=False)
        self.username_regex = re.compile(
            r"(user(?:name)?)=(?:[^ ,]+\\)?([^ ,]+)")

    def _get_device_path(self, connection_info):
        smbfs_share = connection_info['data']['export']
        mount_path = self._get_mount_path(smbfs_share)
        volume_path = os.path.join(mount_path,
                                   connection_info['data']['name'])
        return volume_path

    def _get_mount_path(self, smbfs_share):
        mount_path = os.path.join(CONF.libvirt.smbfs_mount_point_base,
                                  utils.get_hash_str(smbfs_share))
        return mount_path

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtSMBFSVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.driver_cache = 'writethrough'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume."""
        smbfs_share = connection_info['data']['export']
        mount_path = self._get_mount_path(smbfs_share)

        if not libvirt_utils.is_mounted(mount_path, smbfs_share):
            mount_options = self._parse_mount_options(connection_info)
            remotefs.mount_share(mount_path, smbfs_share,
                                 export_type='cifs', options=mount_options)

        device_path = self._get_device_path(connection_info)
        connection_info['data']['device_path'] = device_path

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""
        smbfs_share = connection_info['data']['export']
        mount_path = self._get_mount_path(smbfs_share)
        remotefs.unmount_share(mount_path, smbfs_share)

    def _parse_mount_options(self, connection_info):
        mount_options = " ".join(
            [connection_info['data'].get('options') or '',
             CONF.libvirt.smbfs_mount_options])

        if not self.username_regex.findall(mount_options):
            mount_options = mount_options + ' -o username=guest'
        else:
            # Remove the Domain Name from user name
            mount_options = self.username_regex.sub(r'\1=\2', mount_options)
        return mount_options.strip(", ").split(' ')


class LibvirtAOEVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach AoE volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtAOEVolumeDriver,
              self).__init__(connection, is_block_dev=True)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            'AOE', utils._get_root_helper(),
            device_scan_attempts=CONF.libvirt.num_aoe_discover_tries)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtAOEVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        return conf

    def connect_volume(self, connection_info, mount_device):
        LOG.debug("Calling os-brick to attach AoE Volume")
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached AoE volume %s", device_info)

        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""

        LOG.debug("calling os-brick to detach AoE Volume %s",
                  connection_info)
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected AoE Volume %s", disk_dev)

        super(LibvirtAOEVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)


class LibvirtGlusterfsVolumeDriver(LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for GlusterFS."""

    def __init__(self, connection):
        """Create back-end to glusterfs."""
        super(LibvirtGlusterfsVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def _get_device_path(self, connection_info):
        path = os.path.join(CONF.libvirt.glusterfs_mount_point_base,
            utils.get_hash_str(connection_info['data']['export']))
        path = os.path.join(path, connection_info['data']['name'])
        return path

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtGlusterfsVolumeDriver,
                     self).get_config(connection_info, disk_info)

        data = connection_info['data']

        if 'gluster' in CONF.libvirt.qemu_allowed_storage_drivers:
            vol_name = data['export'].split('/')[1]
            source_host = data['export'].split('/')[0][:-1]

            conf.source_ports = ['24007']
            conf.source_type = 'network'
            conf.source_protocol = 'gluster'
            conf.source_hosts = [source_host]
            conf.source_name = '%s/%s' % (vol_name, data['name'])
        else:
            conf.source_type = 'file'
            conf.source_path = connection_info['data']['device_path']

        conf.driver_format = connection_info['data'].get('format', 'raw')

        return conf

    def connect_volume(self, connection_info, mount_device):
        data = connection_info['data']

        if 'gluster' not in CONF.libvirt.qemu_allowed_storage_drivers:
            self._ensure_mounted(data['export'], data.get('options'))
            connection_info['data']['device_path'] = \
                self._get_device_path(connection_info)

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""

        if 'gluster' in CONF.libvirt.qemu_allowed_storage_drivers:
            return

        export = connection_info['data']['export']
        mount_path = os.path.join(CONF.libvirt.glusterfs_mount_point_base,
                                  utils.get_hash_str(export))

        try:
            utils.execute('umount', mount_path, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if 'target is busy' in exc.message:
                LOG.debug("The GlusterFS share %s is still in use.", export)
            else:
                LOG.exception(_LE("Couldn't unmount the GlusterFS share %s"),
                              export)

    def _ensure_mounted(self, glusterfs_export, options=None):
        """@type glusterfs_export: string
           @type options: string
        """
        mount_path = os.path.join(CONF.libvirt.glusterfs_mount_point_base,
                                  utils.get_hash_str(glusterfs_export))
        if not libvirt_utils.is_mounted(mount_path, glusterfs_export):
            self._mount_glusterfs(mount_path, glusterfs_export,
                                  options, ensure=True)
        return mount_path

    def _mount_glusterfs(self, mount_path, glusterfs_share,
                         options=None, ensure=False):
        """Mount glusterfs export to mount path."""
        utils.execute('mkdir', '-p', mount_path)

        gluster_cmd = ['mount', '-t', 'glusterfs']
        if options is not None:
            gluster_cmd.extend(options.split(' '))
        gluster_cmd.extend([glusterfs_share, mount_path])

        try:
            utils.execute(*gluster_cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.message:
                LOG.warn(_LW("%s is already mounted"), glusterfs_share)
            else:
                raise
