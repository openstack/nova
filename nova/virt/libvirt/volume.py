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

import glob
import os
import time
import urllib2

from oslo.config import cfg
import six
import six.moves.urllib.parse as urlparse

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common.gettextutils import _LW
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common import processutils
from nova import paths
from nova.storage import linuxscsi
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import utils as virtutils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume',
               deprecated_group='DEFAULT'),
    cfg.IntOpt('num_iser_scan_tries',
               default=5,
               help='Number of times to rescan iSER target to find volume',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt UUID of the secret for the rbd_user'
                    'volumes',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the NFS volume is mounted on the'
               ' compute node',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('nfs_mount_options',
               help='Mount options passedf to the NFS client. See section '
                    'of the nfs man page for details',
               deprecated_group='DEFAULT'),
    cfg.IntOpt('num_aoe_discover_tries',
               default=3,
               help='Number of times to rediscover AoE target to find volume',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the glusterfs volume is mounted on the '
                    'compute node',
               deprecated_group='DEFAULT'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI volume',
                deprecated_group='DEFAULT',
                deprecated_name='libvirt_iscsi_use_multipath'),
    cfg.BoolOpt('iser_use_multipath',
                default=False,
                help='Use multipath connection of the iSER volume',
                deprecated_group='DEFAULT',
                deprecated_name='libvirt_iser_use_multipath'),
    cfg.StrOpt('scality_sofs_config',
               help='Path or URL to Scality SOFS configuration file',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted',
               deprecated_group='DEFAULT'),
    cfg.ListOpt('qemu_allowed_storage_drivers',
                default=[],
                help='Protocols listed here will be accessed directly '
                     'from QEMU. Currently supported protocols: [gluster]',
                deprecated_group='DEFAULT')
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class LibvirtBaseVolumeDriver(object):
    """Base class for volume drivers."""
    def __init__(self, connection, is_block_dev):
        self.connection = connection
        self.is_block_dev = is_block_dev

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""

        conf = vconfig.LibvirtConfigGuestDisk()
        conf.driver_name = virtutils.pick_disk_driver_name(
            self.connection.get_hypervisor_version(),
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
                for k, v in specs.iteritems():
                    if k in tune_opts:
                        new_key = 'disk_' + k
                        setattr(conf, new_key, v)
            else:
                LOG.warn(_('Unknown content in connection_info/'
                           'qos_specs: %s') % specs)

        # Extract access_mode control parameters
        if 'access_mode' in data and data['access_mode']:
            access_mode = data['access_mode']
            if access_mode in ('ro', 'rw'):
                conf.readonly = access_mode == 'ro'
            else:
                msg = (_('Unknown content in connection_info/access_mode: %s')
                       % access_mode)
                LOG.error(msg)
                raise exception.InvalidVolumeAccessMode(
                                                    access_mode=access_mode)

        return conf

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""
        pass


class LibvirtVolumeDriver(LibvirtBaseVolumeDriver):
    """Class for volumes backed by local file."""
    def __init__(self, connection):
        super(LibvirtVolumeDriver,
              self).__init__(connection, is_block_dev=True)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume to a local device."""
        conf = super(LibvirtVolumeDriver,
                     self).connect_volume(connection_info,
                                          disk_info)
        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        return conf


class LibvirtFakeVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach fake volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtFakeVolumeDriver,
              self).__init__(connection, is_block_dev=True)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume to a fake device."""
        conf = super(LibvirtFakeVolumeDriver,
                     self).connect_volume(connection_info,
                                          disk_info)
        conf.source_type = "network"
        conf.source_protocol = "fake"
        conf.source_name = "fake"
        return conf


class LibvirtNetVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtNetVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def connect_volume(self, connection_info, disk_info):
        conf = super(LibvirtNetVolumeDriver,
                     self).connect_volume(connection_info,
                                          disk_info)
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
        if auth_enabled:
            conf.auth_username = (conf.auth_username or
                                  netdisk_properties['auth_username'])
            conf.auth_secret_type = netdisk_properties['secret_type']
            conf.auth_secret_uuid = (conf.auth_secret_uuid or
                                     netdisk_properties['secret_uuid'])
        return conf


class LibvirtISCSIVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtISCSIVolumeDriver, self).__init__(connection,
                                                       is_block_dev=True)
        self.num_scan_tries = CONF.libvirt.num_iscsi_scan_tries
        self.use_multipath = CONF.libvirt.iscsi_use_multipath

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug(_("iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s"),
                  {'command': iscsi_command, 'out': out, 'err': err})
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value,
                         **kwargs):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command, **kwargs)

    def _get_target_portals_from_iscsiadm_output(self, output):
        # return both portals and iqns
        return [line.split() for line in output.splitlines()]

    @utils.synchronized('connect_volume')
    def connect_volume(self, connection_info, disk_info):
        """Attach the volume to instance_name."""
        conf = super(LibvirtISCSIVolumeDriver,
                     self).connect_volume(connection_info,
                                          disk_info)

        iscsi_properties = connection_info['data']

        if self.use_multipath:
            #multipath installed, discovering other targets if available
            #multipath should be configured on the nova-compute node,
            #in order to fit storage vendor
            out = self._run_iscsiadm_bare(['-m',
                                          'discovery',
                                          '-t',
                                          'sendtargets',
                                          '-p',
                                          iscsi_properties['target_portal']],
                                          check_exit_code=[0, 255])[0] \
                or ""

            for ip, iqn in self._get_target_portals_from_iscsiadm_output(out):
                props = iscsi_properties.copy()
                props['target_portal'] = ip
                props['target_iqn'] = iqn
                self._connect_to_iscsi_portal(props)

            self._rescan_iscsi()
        else:
            self._connect_to_iscsi_portal(iscsi_properties)

            # Detect new/resized LUNs for existing sessions
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

        host_device = self._get_host_device(iscsi_properties)

        # The /dev/disk/by-path/... node is not always present immediately
        # TODO(justinsb): This retry-with-delay is a pattern, move to utils?
        tries = 0
        disk_dev = disk_info['dev']
        while not os.path.exists(host_device):
            if tries >= self.num_scan_tries:
                raise exception.NovaException(_("iSCSI device not found at %s")
                                              % (host_device))

            LOG.warn(_("ISCSI volume not yet found at: %(disk_dev)s. "
                       "Will rescan & retry.  Try number: %(tries)s"),
                     {'disk_dev': disk_dev,
                      'tries': tries})

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

            tries = tries + 1
            if not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(disk_dev)s "
                        "(after %(tries)s rescans)"),
                      {'disk_dev': disk_dev,
                       'tries': tries})

        if self.use_multipath:
            #we use the multipath device instead of the single path device
            self._rescan_multipath()

            multipath_device = self._get_multipath_device_name(host_device)

            if multipath_device is not None:
                host_device = multipath_device

        conf.source_type = "block"
        conf.source_path = host_device
        return conf

    @utils.synchronized('connect_volume')
    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""
        iscsi_properties = connection_info['data']
        host_device = self._get_host_device(iscsi_properties)
        multipath_device = None
        if self.use_multipath:
            multipath_device = self._get_multipath_device_name(host_device)

        super(LibvirtISCSIVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)

        if self.use_multipath and multipath_device:
            return self._disconnect_volume_multipath_iscsi(iscsi_properties,
                                                           multipath_device)

        # NOTE(vish): Only disconnect from the target if no luns from the
        #             target are in use.
        device_prefix = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-" %
                         (iscsi_properties['target_portal'],
                          iscsi_properties['target_iqn']))
        devices = self.connection.get_all_block_devices()
        devices = [dev for dev in devices if dev.startswith(device_prefix)]
        if not devices:
            self._disconnect_from_iscsi_portal(iscsi_properties)
        elif host_device not in devices:
            # Delete device if LUN is not in use by another instance
            self._delete_device(host_device)

    def _delete_device(self, device_path):
        device_name = os.path.basename(os.path.realpath(device_path))
        delete_control = '/sys/block/' + device_name + '/device/delete'
        if os.path.exists(delete_control):
            # Copy '1' from stdin to the device delete control file
            utils.execute('cp', '/dev/stdin', delete_control,
                          process_input='1', run_as_root=True)
        else:
            LOG.warn(_("Unable to delete volume device %s"), device_name)

    def _remove_multipath_device_descriptor(self, disk_descriptor):
        disk_descriptor = disk_descriptor.replace('/dev/mapper/', '')
        try:
            self._run_multipath(['-f', disk_descriptor],
                                check_exit_code=[0, 1])
        except exception.ProcessExecutionError as exc:
            # Because not all cinder drivers need to remove the dev mapper,
            # here just logs a warning to avoid affecting those drivers in
            # exceptional cases.
            LOG.warn(_('Failed to remove multipath device descriptor '
                       '%(dev_mapper)s. Exception message: %(msg)s')
                     % {'dev_mapper': disk_descriptor,
                        'msg': exc.message})

    def _disconnect_volume_multipath_iscsi(self, iscsi_properties,
                                           multipath_device):
        self._rescan_iscsi()
        self._rescan_multipath()
        block_devices = self.connection.get_all_block_devices()
        devices = []
        for dev in block_devices:
            if "/mapper/" in dev:
                devices.append(dev)
            else:
                mpdev = self._get_multipath_device_name(dev)
                if mpdev:
                    devices.append(mpdev)

        # Do a discovery to find all targets.
        # Targets for multiple paths for the same multipath device
        # may not be the same.
        out = self._run_iscsiadm_bare(['-m',
                                      'discovery',
                                      '-t',
                                      'sendtargets',
                                      '-p',
                                      iscsi_properties['target_portal']],
                                      check_exit_code=[0, 255])[0] \
            or ""

        ips_iqns = self._get_target_portals_from_iscsiadm_output(out)

        if not devices:
            # disconnect if no other multipath devices
            self._disconnect_mpath(iscsi_properties, ips_iqns)
            return

        # Get a target for all other multipath devices
        other_iqns = [self._get_multipath_iqn(device)
                      for device in devices]
        # Get all the targets for the current multipath device
        current_iqns = [iqn for ip, iqn in ips_iqns]

        in_use = False
        for current in current_iqns:
            if current in other_iqns:
                in_use = True
                break

        # If no other multipath device attached has the same iqn
        # as the current device
        if not in_use:
            # disconnect if no other multipath devices with same iqn
            self._disconnect_mpath(iscsi_properties, ips_iqns)
            return
        elif multipath_device not in devices:
            # delete the devices associated w/ the unused multipath
            self._delete_mpath(iscsi_properties, multipath_device, ips_iqns)

        # else do not disconnect iscsi portals,
        # as they are used for other luns,
        # just remove multipath mapping device descriptor
        self._remove_multipath_device_descriptor(multipath_device)
        return

    def _connect_to_iscsi_portal(self, iscsi_properties):
        # NOTE(vish): If we are on the same host as nova volume, the
        #             discovery makes the target so we don't need to
        #             run --op new. Therefore, we check to see if the
        #             target exists, and if we get 255 (Not Found), then
        #             we run --op new. This will also happen if another
        #             volume is using the same target.
        try:
            self._run_iscsiadm(iscsi_properties, ())
        except processutils.ProcessExecutionError as exc:
            # iscsiadm returns 21 for "No records found" after version 2.0-871
            if exc.exit_code in [21, 255]:
                self._reconnect(iscsi_properties)
            else:
                raise

        if iscsi_properties.get('auth_method'):
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.authmethod",
                                  iscsi_properties['auth_method'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.username",
                                  iscsi_properties['auth_username'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.password",
                                  iscsi_properties['auth_password'])

        #duplicate logins crash iscsiadm after load,
        #so we scan active sessions to see if the node is logged in.
        out = self._run_iscsiadm_bare(["-m", "session"],
                                      run_as_root=True,
                                      check_exit_code=[0, 1, 21])[0] or ""

        portals = [{'portal': p.split(" ")[2], 'iqn': p.split(" ")[3]}
                   for p in out.splitlines() if p.startswith("tcp:")]

        stripped_portal = iscsi_properties['target_portal'].split(",")[0]
        if len(portals) == 0 or len([s for s in portals
                                     if stripped_portal ==
                                     s['portal'].split(",")[0]
                                     and
                                     s['iqn'] ==
                                     iscsi_properties['target_iqn']]
                                    ) == 0:
            try:
                self._run_iscsiadm(iscsi_properties,
                                   ("--login",),
                                   check_exit_code=[0, 255])
            except processutils.ProcessExecutionError as err:
                #as this might be one of many paths,
                #only set successful logins to startup automatically
                if err.exit_code in [15]:
                    self._iscsiadm_update(iscsi_properties,
                                          "node.startup",
                                          "automatic")
                    return

            self._iscsiadm_update(iscsi_properties,
                                  "node.startup",
                                  "automatic")

    def _disconnect_from_iscsi_portal(self, iscsi_properties):
        self._iscsiadm_update(iscsi_properties, "node.startup", "manual",
                              check_exit_code=[0, 21, 255])
        self._run_iscsiadm(iscsi_properties, ("--logout",),
                           check_exit_code=[0, 21, 255])
        self._run_iscsiadm(iscsi_properties, ('--op', 'delete'),
                           check_exit_code=[0, 21, 255])

    def _get_multipath_device_name(self, single_path_device):
        device = os.path.realpath(single_path_device)

        out = self._run_multipath(['-ll',
                                  device],
                                  check_exit_code=[0, 1])[0]
        mpath_line = [line for line in out.splitlines()
                      if "scsi_id" not in line]  # ignore udev errors
        if len(mpath_line) > 0 and len(mpath_line[0]) > 0:
            return "/dev/mapper/%s" % mpath_line[0].split(" ")[0]

        return None

    def _get_iscsi_devices(self):
        try:
            devices = list(os.walk('/dev/disk/by-path'))[0][-1]
        except IndexError:
            return []
        return [entry for entry in devices if entry.startswith("ip-")]

    def _delete_mpath(self, iscsi_properties, multipath_device, ips_iqns):
        entries = self._get_iscsi_devices()
        # Loop through ips_iqns to construct all paths
        iqn_luns = []
        for ip, iqn in ips_iqns:
            iqn_lun = '%s-lun-%s' % (iqn,
                                     iscsi_properties.get('target_lun', 0))
            iqn_luns.append(iqn_lun)
        for dev in ['/dev/disk/by-path/%s' % dev for dev in entries]:
            for iqn_lun in iqn_luns:
                if iqn_lun in dev:
                    self._delete_device(dev)

        self._rescan_multipath()

    def _disconnect_mpath(self, iscsi_properties, ips_iqns):
        for ip, iqn in ips_iqns:
            props = iscsi_properties.copy()
            props['target_portal'] = ip
            props['target_iqn'] = iqn
            self._disconnect_from_iscsi_portal(props)

        self._rescan_multipath()

    def _get_multipath_iqn(self, multipath_device):
        entries = self._get_iscsi_devices()
        for entry in entries:
            entry_real_path = os.path.realpath("/dev/disk/by-path/%s" % entry)
            entry_multipath = self._get_multipath_device_name(entry_real_path)
            if entry_multipath == multipath_device:
                return entry.split("iscsi-")[1].split("-lun")[0]
        return None

    def _run_iscsiadm_bare(self, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('iscsiadm',
                                   *iscsi_command,
                                   run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug(_("iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s"),
                  {'command': iscsi_command, 'out': out, 'err': err})
        return (out, err)

    def _run_multipath(self, multipath_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('multipath',
                                   *multipath_command,
                                   run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug(_("multipath %(command)s: stdout=%(out)s stderr=%(err)s"),
                  {'command': multipath_command, 'out': out, 'err': err})
        return (out, err)

    def _rescan_iscsi(self):
        self._run_iscsiadm_bare(('-m', 'node', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])
        self._run_iscsiadm_bare(('-m', 'session', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])

    def _rescan_multipath(self):
        self._run_multipath('-r', check_exit_code=[0, 1, 21])

    def _get_host_device(self, iscsi_properties):
        return ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-%s" %
                (iscsi_properties['target_portal'],
                 iscsi_properties['target_iqn'],
                 iscsi_properties.get('target_lun', 0)))

    def _reconnect(self, iscsi_properties):
        self._run_iscsiadm(iscsi_properties, ('--op', 'new'))


class LibvirtISERVolumeDriver(LibvirtISCSIVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtISERVolumeDriver, self).__init__(connection)
        self.num_scan_tries = CONF.libvirt.num_iser_scan_tries
        self.use_multipath = CONF.libvirt.iser_use_multipath

    def _get_multipath_iqn(self, multipath_device):
        entries = self._get_iscsi_devices()
        for entry in entries:
            entry_real_path = os.path.realpath("/dev/disk/by-path/%s" % entry)
            entry_multipath = self._get_multipath_device_name(entry_real_path)
            if entry_multipath == multipath_device:
                return entry.split("iser-")[1].split("-lun")[0]
        return None

    def _get_host_device(self, iser_properties):
        time.sleep(1)
        host_device = None
        device = ("ip-%s-iscsi-%s-lun-%s" %
                  (iser_properties['target_portal'],
                   iser_properties['target_iqn'],
                   iser_properties.get('target_lun', 0)))
        look_for_device = glob.glob('/dev/disk/by-path/*%s' % device)
        if look_for_device:
            host_device = look_for_device[0]
        return host_device

    def _reconnect(self, iser_properties):
        self._run_iscsiadm(iser_properties,
                           ('--interface', 'iser', '--op', 'new'))


class LibvirtNFSVolumeDriver(LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for NFS."""

    def __init__(self, connection):
        """Create back-end to nfs."""
        super(LibvirtNFSVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""
        conf = super(LibvirtNFSVolumeDriver,
                     self).connect_volume(connection_info,
                                          disk_info)
        options = connection_info['data'].get('options')
        path = self._ensure_mounted(connection_info['data']['export'], options)
        path = os.path.join(path, connection_info['data']['name'])
        conf.source_type = 'file'
        conf.source_path = path
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""

        export = connection_info['data']['export']
        mount_path = os.path.join(CONF.libvirt.nfs_mount_point_base,
                                  utils.get_hash_str(export))

        try:
            utils.execute('umount', mount_path, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if 'target is busy' in exc.message:
                LOG.debug(_("The NFS share %s is still in use."), export)
            else:
                LOG.exception(_("Couldn't unmount the NFS share %s"), export)

    def _ensure_mounted(self, nfs_export, options=None):
        """@type nfs_export: string
           @type options: string
        """
        mount_path = os.path.join(CONF.libvirt.nfs_mount_point_base,
                                  utils.get_hash_str(nfs_export))
        if not virtutils.is_mounted(mount_path, nfs_export):
            self._mount_nfs(mount_path, nfs_export, options, ensure=True)
        return mount_path

    def _mount_nfs(self, mount_path, nfs_share, options=None, ensure=False):
        """Mount nfs export to mount path."""
        utils.execute('mkdir', '-p', mount_path)

        # Construct the NFS mount command.
        nfs_cmd = ['mount', '-t', 'nfs']
        if CONF.libvirt.nfs_mount_options is not None:
            nfs_cmd.extend(['-o', CONF.libvirt.nfs_mount_options])
        if options is not None:
            nfs_cmd.extend(options.split(' '))
        nfs_cmd.extend([nfs_share, mount_path])

        try:
            utils.execute(*nfs_cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.message:
                LOG.warn(_("%s is already mounted"), nfs_share)
            else:
                raise


class LibvirtAOEVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach AoE volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtAOEVolumeDriver,
              self).__init__(connection, is_block_dev=True)

    def _aoe_discover(self):
        """Call aoe-discover (aoe-tools) AoE Discover."""
        (out, err) = utils.execute('aoe-discover',
                                   run_as_root=True, check_exit_code=0)
        return (out, err)

    def _aoe_revalidate(self, aoedev):
        """Revalidate the LUN Geometry (When an AoE ID is reused)."""
        (out, err) = utils.execute('aoe-revalidate', aoedev,
                                   run_as_root=True, check_exit_code=0)
        return (out, err)

    def connect_volume(self, connection_info, mount_device):
        shelf = connection_info['data']['target_shelf']
        lun = connection_info['data']['target_lun']
        aoedev = 'e%s.%s' % (shelf, lun)
        aoedevpath = '/dev/etherd/%s' % (aoedev)

        if os.path.exists(aoedevpath):
            # NOTE(jbr_): If aoedevpath already exists, revalidate the LUN.
            self._aoe_revalidate(aoedev)
        else:
            # NOTE(jbr_): If aoedevpath does not exist, do a discover.
            self._aoe_discover()

        #NOTE(jbr_): Device path is not always present immediately
        def _wait_for_device_discovery(aoedevpath, mount_device):
            tries = self.tries
            if os.path.exists(aoedevpath):
                raise loopingcall.LoopingCallDone()

            if self.tries >= CONF.libvirt.num_aoe_discover_tries:
                raise exception.NovaException(_("AoE device not found at %s") %
                                                (aoedevpath))
            LOG.warn(_("AoE volume not yet found at: %(aoedevpath)s. "
                       "Try number: %(tries)s"),
                     {'aoedevpath': aoedevpath,
                      'tries': tries})

            self._aoe_discover()
            self.tries = self.tries + 1

        self.tries = 0
        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_device_discovery, aoedevpath, mount_device)
        timer.start(interval=2).wait()

        tries = self.tries
        if tries != 0:
            LOG.debug(_("Found AoE device %(aoedevpath)s "
                        "(after %(tries)s rediscover)"),
                      {'aoedevpath': aoedevpath,
                       'tries': tries})

        conf = super(LibvirtAOEVolumeDriver,
                     self).connect_volume(connection_info, mount_device)
        conf.source_type = "block"
        conf.source_path = aoedevpath
        return conf


class LibvirtGlusterfsVolumeDriver(LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for GlusterFS."""

    def __init__(self, connection):
        """Create back-end to glusterfs."""
        super(LibvirtGlusterfsVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def connect_volume(self, connection_info, mount_device):
        """Connect the volume. Returns xml for libvirt."""
        conf = super(LibvirtGlusterfsVolumeDriver,
                     self).connect_volume(connection_info, mount_device)

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
            path = self._ensure_mounted(data['export'], data.get('options'))
            path = os.path.join(path, data['name'])
            conf.source_type = 'file'
            conf.source_path = path

        conf.driver_format = connection_info['data'].get('format', 'raw')

        return conf

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
                LOG.debug(_("The GlusterFS share %s is still in use."), export)
            else:
                LOG.exception(_("Couldn't unmount the GlusterFS share %s"),
                              export)

    def _ensure_mounted(self, glusterfs_export, options=None):
        """@type glusterfs_export: string
           @type options: string
        """
        mount_path = os.path.join(CONF.libvirt.glusterfs_mount_point_base,
                                  utils.get_hash_str(glusterfs_export))
        if not virtutils.is_mounted(mount_path, glusterfs_export):
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
                LOG.warn(_("%s is already mounted"), glusterfs_share)
            else:
                raise


class LibvirtFibreChannelVolumeDriver(LibvirtBaseVolumeDriver):
    """Driver to attach Fibre Channel Network volumes to libvirt."""

    def __init__(self, connection):
        super(LibvirtFibreChannelVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def _get_pci_num(self, hba):
        # NOTE(walter-boring)
        # device path is in format of
        # /sys/devices/pci0000:00/0000:00:03.0/0000:05:00.3/host2/fc_host/host2
        # sometimes an extra entry exists before the host2 value
        # we always want the value prior to the host2 value
        pci_num = None
        if hba is not None:
            if "device_path" in hba:
                index = 0
                device_path = hba['device_path'].split('/')
                for value in device_path:
                    if value.startswith('host'):
                        break
                    index = index + 1

                if index > 0:
                    pci_num = device_path[index - 1]

        return pci_num

    @utils.synchronized('connect_volume')
    def connect_volume(self, connection_info, disk_info):
        """Attach the volume to instance_name."""
        fc_properties = connection_info['data']
        mount_device = disk_info["dev"]

        ports = fc_properties['target_wwn']
        wwns = []
        # we support a list of wwns or a single wwn
        if isinstance(ports, list):
            for wwn in ports:
                wwns.append(str(wwn))
        elif isinstance(ports, six.string_types):
            wwns.append(str(ports))

        # We need to look for wwns on every hba
        # because we don't know ahead of time
        # where they will show up.
        hbas = virtutils.get_fc_hbas_info()
        host_devices = []
        for hba in hbas:
            pci_num = self._get_pci_num(hba)
            if pci_num is not None:
                for wwn in wwns:
                    target_wwn = "0x%s" % wwn.lower()
                    host_device = ("/dev/disk/by-path/pci-%s-fc-%s-lun-%s" %
                                  (pci_num,
                                   target_wwn,
                                   fc_properties.get('target_lun', 0)))
                    host_devices.append(host_device)

        if len(host_devices) == 0:
            # this is empty because we don't have any FC HBAs
            msg = _("We are unable to locate any Fibre Channel devices")
            raise exception.NovaException(msg)

        # The /dev/disk/by-path/... node is not always present immediately
        # We only need to find the first device.  Once we see the first device
        # multipath will have any others.
        def _wait_for_device_discovery(host_devices, mount_device):
            tries = self.tries
            for device in host_devices:
                LOG.debug(_("Looking for Fibre Channel dev %(device)s"),
                          {'device': device})
                if os.path.exists(device):
                    self.host_device = device
                    # get the /dev/sdX device.  This is used
                    # to find the multipath device.
                    self.device_name = os.path.realpath(device)
                    raise loopingcall.LoopingCallDone()

            if self.tries >= CONF.libvirt.num_iscsi_scan_tries:
                msg = _("Fibre Channel device not found.")
                raise exception.NovaException(msg)

            LOG.warn(_("Fibre volume not yet found at: %(mount_device)s. "
                       "Will rescan & retry.  Try number: %(tries)s"),
                     {'mount_device': mount_device,
                      'tries': tries})

            linuxscsi.rescan_hosts(hbas)
            self.tries = self.tries + 1

        self.host_device = None
        self.device_name = None
        self.tries = 0
        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_device_discovery, host_devices, mount_device)
        timer.start(interval=2).wait()

        tries = self.tries
        if self.host_device is not None and self.device_name is not None:
            LOG.debug(_("Found Fibre Channel volume %(mount_device)s "
                        "(after %(tries)s rescans)"),
                      {'mount_device': mount_device,
                       'tries': tries})

        # see if the new drive is part of a multipath
        # device.  If so, we'll use the multipath device.
        mdev_info = linuxscsi.find_multipath_device(self.device_name)
        if mdev_info is not None:
            LOG.debug(_("Multipath device discovered %(device)s")
                      % {'device': mdev_info['device']})
            device_path = mdev_info['device']
            connection_info['data']['devices'] = mdev_info['devices']
            connection_info['data']['multipath_id'] = mdev_info['id']
        else:
            # we didn't find a multipath device.
            # so we assume the kernel only sees 1 device
            device_path = self.host_device
            device_info = linuxscsi.get_device_info(self.device_name)
            connection_info['data']['devices'] = [device_info]

        conf = super(LibvirtFibreChannelVolumeDriver,
                     self).connect_volume(connection_info, disk_info)

        conf.source_type = "block"
        conf.source_path = device_path
        return conf

    @utils.synchronized('connect_volume')
    def disconnect_volume(self, connection_info, mount_device):
        """Detach the volume from instance_name."""
        super(LibvirtFibreChannelVolumeDriver,
              self).disconnect_volume(connection_info, mount_device)

        # If this is a multipath device, we need to search again
        # and make sure we remove all the devices. Some of them
        # might not have shown up at attach time.
        if 'multipath_id' in connection_info['data']:
            multipath_id = connection_info['data']['multipath_id']
            mdev_info = linuxscsi.find_multipath_device(multipath_id)
            devices = mdev_info['devices']
            LOG.debug(_("devices to remove = %s"), devices)
        else:
            # only needed when multipath-tools work improperly
            devices = connection_info['data'].get('devices', [])
            LOG.warn(_LW("multipath-tools probably work improperly. "
                       "devices to remove = %s.") % devices)

        # There may have been more than 1 device mounted
        # by the kernel for this volume.  We have to remove
        # all of them
        for device in devices:
            linuxscsi.remove_device(device)


class LibvirtScalityVolumeDriver(LibvirtBaseVolumeDriver):
    """Scality SOFS Nova driver. Provide hypervisors with access
    to sparse files on SOFS.
    """

    def __init__(self, connection):
        """Create back-end to SOFS and check connection."""
        super(LibvirtScalityVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""
        self._check_prerequisites()
        self._mount_sofs()
        conf = super(LibvirtScalityVolumeDriver,
                     self).connect_volume(connection_info, disk_info)
        path = os.path.join(CONF.libvirt.scality_sofs_mount_point,
                            connection_info['data']['sofs_path'])
        conf.source_type = 'file'
        conf.source_path = path

        # The default driver cache policy is 'none', and this causes
        # qemu/kvm to open the volume file with O_DIRECT, which is
        # rejected by FUSE (on kernels older than 3.3). Scality SOFS
        # is FUSE based, so we must provide a more sensible default.
        conf.driver_cache = 'writethrough'

        return conf

    def _check_prerequisites(self):
        """Sanity checks before attempting to mount SOFS."""

        # config is mandatory
        config = CONF.libvirt.scality_sofs_config
        if not config:
            msg = _("Value required for 'scality_sofs_config'")
            LOG.warn(msg)
            raise exception.NovaException(msg)

        # config can be a file path or a URL, check it
        if urlparse.urlparse(config).scheme == '':
            # turn local path into URL
            config = 'file://%s' % config
        try:
            urllib2.urlopen(config, timeout=5).close()
        except urllib2.URLError as e:
            msg = _("Cannot access 'scality_sofs_config': %s") % e
            LOG.warn(msg)
            raise exception.NovaException(msg)

        # mount.sofs must be installed
        if not os.access('/sbin/mount.sofs', os.X_OK):
            msg = _("Cannot execute /sbin/mount.sofs")
            LOG.warn(msg)
            raise exception.NovaException(msg)

    def _mount_sofs(self):
        config = CONF.libvirt.scality_sofs_config
        mount_path = CONF.libvirt.scality_sofs_mount_point
        sysdir = os.path.join(mount_path, 'sys')

        if not os.path.isdir(mount_path):
            utils.execute('mkdir', '-p', mount_path)
        if not os.path.isdir(sysdir):
            utils.execute('mount', '-t', 'sofs', config, mount_path,
                          run_as_root=True)
        if not os.path.isdir(sysdir):
            msg = _("Cannot mount Scality SOFS, check syslog for errors")
            LOG.warn(msg)
            raise exception.NovaException(msg)
