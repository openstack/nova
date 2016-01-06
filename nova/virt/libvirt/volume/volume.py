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

from oslo_config import cfg
from oslo_log import log as logging
import six

from nova import exception
from nova.i18n import _LE
from nova.i18n import _LW
from nova.virt.libvirt import config as vconfig
import nova.virt.libvirt.driver
from nova.virt.libvirt import host
from nova.virt.libvirt import utils as libvirt_utils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.ListOpt('qemu_allowed_storage_drivers',
                default=[],
                help='Protocols listed here will be accessed directly '
                     'from QEMU. Currently supported protocols: [gluster]'),
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')

SHOULD_LOG_DISCARD_WARNING = True


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
                LOG.warning(_LW('Unknown content in connection_info/'
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

        # Configure usage of discard
        if data.get('discard', False) is True:
            min_qemu = nova.virt.libvirt.driver.MIN_QEMU_DISCARD_VERSION
            min_libvirt = nova.virt.libvirt.driver.MIN_LIBVIRT_DISCARD_VERSION
            if self.connection._host.has_min_version(min_libvirt,
                                                     min_qemu,
                                                     host.HV_DRIVER_QEMU):
                conf.driver_discard = 'unmap'
            else:
                global SHOULD_LOG_DISCARD_WARNING
                if SHOULD_LOG_DISCARD_WARNING:
                    SHOULD_LOG_DISCARD_WARNING = False
                    LOG.warning(_LW('Unable to attach %(type)s volume '
                                    '%(serial)s with discard enabled: qemu '
                                    '%(qemu)s and libvirt %(libvirt)s or '
                                    'later are required.'),
                                {
                        'qemu': min_qemu,
                        'libvirt': min_libvirt,
                        'serial': conf.serial,
                        'type': connection_info['driver_volume_type']
                    })

        return conf

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume."""
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
