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

from os_brick.initiator import connector
from oslo_config import cfg
from oslo_log import log as logging
import six

from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LW
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import utils as libvirt_utils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume'),
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt UUID of the secret for the rbd_user'
                    'volumes'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI volume'),
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
