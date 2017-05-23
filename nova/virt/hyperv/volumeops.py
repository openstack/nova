# Copyright 2012 Pedro Navarro Perez
# Copyright 2013 Cloudbase Solutions Srl
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

"""
Management class for Storage-related functions (attach, detach, etc).
"""
import time

from os_brick.initiator import connector
from os_win import utilsfactory
from oslo_log import log as logging
from oslo_utils import strutils

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt import driver
from nova.virt.hyperv import constants

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class VolumeOps(object):
    """Management class for Volume-related tasks
    """

    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._default_root_device = 'vda'
        self.volume_drivers = {
            constants.STORAGE_PROTOCOL_SMBFS: SMBFSVolumeDriver(),
            constants.STORAGE_PROTOCOL_ISCSI: ISCSIVolumeDriver(),
            constants.STORAGE_PROTOCOL_FC: FCVolumeDriver()}

    def _get_volume_driver(self, connection_info):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        return self.volume_drivers[driver_type]

    def attach_volumes(self, volumes, instance_name):
        for vol in volumes:
            self.attach_volume(vol['connection_info'], instance_name)

    def disconnect_volumes(self, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            self.disconnect_volume(vol['connection_info'])

    def attach_volume(self, connection_info, instance_name,
                      disk_bus=constants.CTRL_TYPE_SCSI):
        tries_left = CONF.hyperv.volume_attach_retry_count + 1

        while tries_left:
            try:
                self._attach_volume(connection_info,
                                    instance_name,
                                    disk_bus)
                break
            except Exception as ex:
                tries_left -= 1
                if not tries_left:
                    LOG.exception(
                        _("Failed to attach volume %(connection_info)s "
                          "to instance %(instance_name)s. "),
                        {'connection_info':
                            strutils.mask_dict_password(connection_info),
                         'instance_name': instance_name})

                    self.disconnect_volume(connection_info)
                    raise exception.VolumeAttachFailed(
                        volume_id=connection_info['serial'],
                        reason=ex)
                else:
                    LOG.warning(
                        "Failed to attach volume %(connection_info)s "
                        "to instance %(instance_name)s. "
                        "Tries left: %(tries_left)s.",
                        {'connection_info': strutils.mask_dict_password(
                             connection_info),
                         'instance_name': instance_name,
                         'tries_left': tries_left})

                    time.sleep(CONF.hyperv.volume_attach_retry_interval)

    def _attach_volume(self, connection_info, instance_name,
                       disk_bus=constants.CTRL_TYPE_SCSI):
        LOG.debug(
            "Attaching volume: %(connection_info)s to %(instance_name)s",
            {'connection_info': strutils.mask_dict_password(connection_info),
             'instance_name': instance_name})
        volume_driver = self._get_volume_driver(connection_info)
        volume_driver.attach_volume(connection_info,
                                    instance_name,
                                    disk_bus)

        qos_specs = connection_info['data'].get('qos_specs') or {}
        if qos_specs:
            volume_driver.set_disk_qos_specs(connection_info,
                                             qos_specs)

    def disconnect_volume(self, connection_info):
        volume_driver = self._get_volume_driver(connection_info)
        volume_driver.disconnect_volume(connection_info)

    def detach_volume(self, connection_info, instance_name):
        LOG.debug("Detaching volume: %(connection_info)s "
                  "from %(instance_name)s",
                  {'connection_info': strutils.mask_dict_password(
                      connection_info),
                   'instance_name': instance_name})
        volume_driver = self._get_volume_driver(connection_info)
        volume_driver.detach_volume(connection_info, instance_name)
        volume_driver.disconnect_volume(connection_info)

    def fix_instance_volume_disk_paths(self, instance_name, block_device_info):
        # Mapping containing the current disk paths for each volume.
        actual_disk_mapping = self.get_disk_path_mapping(block_device_info)
        if not actual_disk_mapping:
            return

        # Mapping containing virtual disk resource path and the physical
        # disk path for each volume serial number. The physical path
        # associated with this resource may not be the right one,
        # as physical disk paths can get swapped after host reboots.
        vm_disk_mapping = self._vmutils.get_vm_physical_disk_mapping(
            instance_name)

        for serial, vm_disk in vm_disk_mapping.items():
            actual_disk_path = actual_disk_mapping[serial]
            if vm_disk['mounted_disk_path'] != actual_disk_path:
                self._vmutils.set_disk_host_res(vm_disk['resource_path'],
                                                actual_disk_path)

    def get_volume_connector(self):
        # NOTE(lpetrut): the Windows os-brick connectors
        # do not use a root helper.
        conn = connector.get_connector_properties(
            root_helper=None,
            my_ip=CONF.my_block_storage_ip,
            multipath=CONF.hyperv.use_multipath_io,
            enforce_multipath=True,
            host=CONF.host)
        return conn

    def connect_volumes(self, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            connection_info = vol['connection_info']
            volume_driver = self._get_volume_driver(connection_info)
            volume_driver.connect_volume(connection_info)

    def get_disk_path_mapping(self, block_device_info):
        block_mapping = driver.block_device_info_get_mapping(block_device_info)
        disk_path_mapping = {}
        for vol in block_mapping:
            connection_info = vol['connection_info']
            disk_serial = connection_info['serial']

            disk_path = self.get_disk_resource_path(connection_info)
            disk_path_mapping[disk_serial] = disk_path
        return disk_path_mapping

    def get_disk_resource_path(self, connection_info):
        volume_driver = self._get_volume_driver(connection_info)
        return volume_driver.get_disk_resource_path(connection_info)

    @staticmethod
    def bytes_per_sec_to_iops(no_bytes):
        # Hyper-v uses normalized IOPS (8 KB increments)
        # as IOPS allocation units.
        return (
            (no_bytes + constants.IOPS_BASE_SIZE - 1) //
            constants.IOPS_BASE_SIZE)

    @staticmethod
    def validate_qos_specs(qos_specs, supported_qos_specs):
        unsupported_specs = set(qos_specs.keys()).difference(
            supported_qos_specs)
        if unsupported_specs:
            LOG.warning('Got unsupported QoS specs: '
                       '%(unsupported_specs)s. '
                       'Supported qos specs: %(supported_qos_specs)s',
                        {'unsupported_specs': unsupported_specs,
                         'supported_qos_specs': supported_qos_specs})


class BaseVolumeDriver(object):
    _is_block_dev = True
    _protocol = None
    _extra_connector_args = {}

    def __init__(self):
        self._conn = None
        self._diskutils = utilsfactory.get_diskutils()
        self._vmutils = utilsfactory.get_vmutils()

    @property
    def _connector(self):
        if not self._conn:
            scan_attempts = CONF.hyperv.mounted_disk_query_retry_count
            scan_interval = CONF.hyperv.mounted_disk_query_retry_interval

            self._conn = connector.InitiatorConnector.factory(
                protocol=self._protocol,
                root_helper=None,
                use_multipath=CONF.hyperv.use_multipath_io,
                device_scan_attempts=scan_attempts,
                device_scan_interval=scan_interval,
                **self._extra_connector_args)
        return self._conn

    def connect_volume(self, connection_info):
        return self._connector.connect_volume(connection_info['data'])

    def disconnect_volume(self, connection_info):
        self._connector.disconnect_volume(connection_info['data'])

    def get_disk_resource_path(self, connection_info):
        disk_paths = self._connector.get_volume_paths(connection_info['data'])
        if not disk_paths:
            vol_id = connection_info['serial']
            err_msg = _("Could not find disk path. Volume id: %s")
            raise exception.DiskNotFound(err_msg % vol_id)

        return self._get_disk_res_path(disk_paths[0])

    def _get_disk_res_path(self, disk_path):
        if self._is_block_dev:
            # We need the Msvm_DiskDrive resource path as this
            # will be used when the disk is attached to an instance.
            disk_number = self._diskutils.get_device_number_from_device_name(
                disk_path)
            disk_res_path = self._vmutils.get_mounted_disk_by_drive_number(
                disk_number)
        else:
            disk_res_path = disk_path
        return disk_res_path

    def attach_volume(self, connection_info, instance_name,
                      disk_bus=constants.CTRL_TYPE_SCSI):
        dev_info = self.connect_volume(connection_info)

        serial = connection_info['serial']
        disk_path = self._get_disk_res_path(dev_info['path'])
        ctrller_path, slot = self._get_disk_ctrl_and_slot(instance_name,
                                                          disk_bus)
        if self._is_block_dev:
            # We need to tag physical disk resources with the volume
            # serial number, in order to be able to retrieve them
            # during live migration.
            self._vmutils.attach_volume_to_controller(instance_name,
                                                      ctrller_path,
                                                      slot,
                                                      disk_path,
                                                      serial=serial)
        else:
            self._vmutils.attach_drive(instance_name,
                                       disk_path,
                                       ctrller_path,
                                       slot)

    def detach_volume(self, connection_info, instance_name):
        disk_path = self.get_disk_resource_path(connection_info)

        LOG.debug("Detaching disk %(disk_path)s "
                  "from instance: %(instance_name)s",
                  dict(disk_path=disk_path,
                       instance_name=instance_name))
        self._vmutils.detach_vm_disk(instance_name, disk_path,
                                     is_physical=self._is_block_dev)

    def _get_disk_ctrl_and_slot(self, instance_name, disk_bus):
        if disk_bus == constants.CTRL_TYPE_IDE:
            # Find the IDE controller for the vm.
            ctrller_path = self._vmutils.get_vm_ide_controller(
                instance_name, 0)
            # Attaching to the first slot
            slot = 0
        else:
            # Find the SCSI controller for the vm
            ctrller_path = self._vmutils.get_vm_scsi_controller(
                instance_name)
            slot = self._vmutils.get_free_controller_slot(ctrller_path)
        return ctrller_path, slot

    def set_disk_qos_specs(self, connection_info, disk_qos_specs):
        LOG.info("The %(protocol)s Hyper-V volume driver "
                 "does not support QoS. Ignoring QoS specs.",
                 dict(protocol=self._protocol))


class ISCSIVolumeDriver(BaseVolumeDriver):
    _is_block_dev = True
    _protocol = constants.STORAGE_PROTOCOL_ISCSI

    def __init__(self, *args, **kwargs):
        self._extra_connector_args = dict(
            initiator_list=CONF.hyperv.iscsi_initiator_list)

        super(ISCSIVolumeDriver, self).__init__(*args, **kwargs)


class SMBFSVolumeDriver(BaseVolumeDriver):
    _is_block_dev = False
    _protocol = constants.STORAGE_PROTOCOL_SMBFS
    _extra_connector_args = dict(local_path_for_loopback=True)

    def export_path_synchronized(f):
        def wrapper(inst, connection_info, *args, **kwargs):
            export_path = inst._get_export_path(connection_info)

            @utils.synchronized(export_path)
            def inner():
                return f(inst, connection_info, *args, **kwargs)
            return inner()
        return wrapper

    def _get_export_path(self, connection_info):
        return connection_info['data']['export'].replace('/', '\\')

    @export_path_synchronized
    def attach_volume(self, *args, **kwargs):
        super(SMBFSVolumeDriver, self).attach_volume(*args, **kwargs)

    @export_path_synchronized
    def disconnect_volume(self, *args, **kwargs):
        # We synchronize those operations based on the share path in order to
        # avoid the situation when a SMB share is unmounted while a volume
        # exported by it is about to be attached to an instance.
        super(SMBFSVolumeDriver, self).disconnect_volume(*args, **kwargs)

    def set_disk_qos_specs(self, connection_info, qos_specs):
        supported_qos_specs = ['total_iops_sec', 'total_bytes_sec']
        VolumeOps.validate_qos_specs(qos_specs, supported_qos_specs)

        total_bytes_sec = int(qos_specs.get('total_bytes_sec') or 0)
        total_iops_sec = int(qos_specs.get('total_iops_sec') or
                             VolumeOps.bytes_per_sec_to_iops(
                                total_bytes_sec))

        if total_iops_sec:
            disk_path = self.get_disk_resource_path(connection_info)
            self._vmutils.set_disk_qos_specs(disk_path, total_iops_sec)


class FCVolumeDriver(BaseVolumeDriver):
    _is_block_dev = True
    _protocol = constants.STORAGE_PROTOCOL_FC
