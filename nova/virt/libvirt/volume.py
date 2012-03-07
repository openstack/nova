# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
import time

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.libvirt import config

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('num_iscsi_scan_tries', 'nova.volume.driver')


class LibvirtVolumeDriver(object):
    """Base class for volume drivers."""
    def __init__(self, connection):
        self.connection = connection

    def _pick_volume_driver(self):
        hypervisor_type = self.connection.get_hypervisor_type().lower()
        return "phy" if hypervisor_type == "xen" else "qemu"

    def connect_volume(self, connection_info, mount_device):
        """Connect the volume. Returns xml for libvirt."""
        conf = config.LibvirtConfigGuestDisk()
        conf.source_type = "block"
        conf.driver_name = self._pick_volume_driver()
        conf.driver_format = "raw"
        conf.driver_cache = "none"
        conf.source_path = connection_info['data']['device_path']
        conf.target_dev = mount_device
        conf.target_bus = "virtio"
        return conf

    def disconnect_volume(self, connection_info, mount_device):
        """Disconnect the volume"""
        pass


class LibvirtFakeVolumeDriver(LibvirtVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def connect_volume(self, connection_info, mount_device):
        conf = config.LibvirtConfigGuestDisk()
        conf.source_type = "network"
        conf.driver_name = "qemu"
        conf.driver_format = "raw"
        conf.driver_cache = "none"
        conf.source_protocol = "fake"
        conf.source_host = "fake"
        conf.target_dev = mount_device
        conf.target_bus = "virtio"
        return conf


class LibvirtNetVolumeDriver(LibvirtVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def connect_volume(self, connection_info, mount_device):
        conf = config.LibvirtConfigGuestDisk()
        conf.source_type = "network"
        conf.driver_name = self._pick_volume_driver()
        conf.driver_format = "raw"
        conf.driver_cache = "none"
        conf.source_protocol = connection_info['driver_volume_type']
        conf.source_host = connection_info['data']['name']
        conf.target_dev = mount_device
        conf.target_bus = "virtio"
        return conf


class LibvirtISCSIVolumeDriver(LibvirtVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command)

    @utils.synchronized('connect_volume')
    def connect_volume(self, connection_info, mount_device):
        """Attach the volume to instance_name"""
        iscsi_properties = connection_info['data']
        # NOTE(vish): If we are on the same host as nova volume, the
        #             discovery makes the target so we don't need to
        #             run --op new. Therefore, we check to see if the
        #             target exists, and if we get 255 (Not Found), then
        #             we run --op new. This will also happen if another
        #             volume is using the same target.
        try:
            self._run_iscsiadm(iscsi_properties, ())
        except exception.ProcessExecutionError as exc:
            # iscsiadm returns 21 for "No records found" after version 2.0-871
            if exc.exit_code in [21, 255]:
                self._run_iscsiadm(iscsi_properties, ('--op', 'new'))
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

        # NOTE(vish): If we have another lun on the same target, we may
        #             have a duplicate login
        self._run_iscsiadm(iscsi_properties, ("--login",),
                           check_exit_code=[0, 255])

        self._iscsiadm_update(iscsi_properties, "node.startup", "automatic")

        host_device = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-%s" %
                        (iscsi_properties['target_portal'],
                         iscsi_properties['target_iqn'],
                         iscsi_properties.get('target_lun', 0)))

        # The /dev/disk/by-path/... node is not always present immediately
        # TODO(justinsb): This retry-with-delay is a pattern, move to utils?
        tries = 0
        while not os.path.exists(host_device):
            if tries >= FLAGS.num_iscsi_scan_tries:
                raise exception.Error(_("iSCSI device not found at %s") %
                                      (host_device))

            LOG.warn(_("ISCSI volume not yet found at: %(mount_device)s. "
                       "Will rescan & retry.  Try number: %(tries)s") %
                     locals())

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

            tries = tries + 1
            if not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(mount_device)s "
                        "(after %(tries)s rescans)") %
                      locals())

        connection_info['data']['device_path'] = host_device
        sup = super(LibvirtISCSIVolumeDriver, self)
        return sup.connect_volume(connection_info, mount_device)

    @utils.synchronized('connect_volume')
    def disconnect_volume(self, connection_info, mount_device):
        """Detach the volume from instance_name"""
        sup = super(LibvirtISCSIVolumeDriver, self)
        sup.disconnect_volume(connection_info, mount_device)
        iscsi_properties = connection_info['data']
        # NOTE(vish): Only disconnect from the target if no luns from the
        #             target are in use.
        device_prefix = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-" %
                         (iscsi_properties['target_portal'],
                          iscsi_properties['target_iqn']))
        devices = self.connection.get_all_block_devices()
        devices = [dev for dev in devices if dev.startswith(device_prefix)]
        if not devices:
            self._iscsiadm_update(iscsi_properties, "node.startup", "manual")
            self._run_iscsiadm(iscsi_properties, ("--logout",),
                               check_exit_code=[0, 255])
            self._run_iscsiadm(iscsi_properties, ('--op', 'delete'),
                               check_exit_code=[0, 255])
