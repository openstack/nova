# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Pedro Navarro Perez
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

from nova import block_device
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import baseops
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeutils

LOG = logging.getLogger(__name__)

hyper_volumeops_opts = [
    cfg.IntOpt('hyperv_attaching_volume_retry_count',
        default=10,
        help='The number of times we retry on attaching volume '),
    cfg.IntOpt('hyperv_wait_between_attach_retry',
        default=5,
        help='The seconds to wait between an volume attachment attempt'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(hyper_volumeops_opts)


class VolumeOps(baseops.BaseOps):
    """
    Management class for Volume-related tasks
    """

    def __init__(self):
        super(VolumeOps, self).__init__()

        self._vmutils = vmutils.VMUtils()
        self._driver = driver
        self._block_device = block_device
        self._time = time
        self._initiator = None
        self._default_root_device = 'vda'
        self._attaching_volume_retry_count = \
            FLAGS.hyperv_attaching_volume_retry_count
        self._wait_between_attach_retry = \
            FLAGS.hyperv_wait_between_attach_retry
        self._volutils = volumeutils.VolumeUtils()

    def attach_boot_volume(self, block_device_info, vm_name):
        """Attach the boot volume to the IDE controller"""
        LOG.debug(_("block device info: %s"), block_device_info)
        ebs_root = self._driver.block_device_info_get_mapping(
            block_device_info)[0]
        connection_info = ebs_root['connection_info']
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        self._volutils.login_storage_target(target_lun, target_iqn,
            target_portal)
        try:
            #Getting the mounted disk
            mounted_disk = self._get_mounted_disk_from_lun(target_iqn,
                target_lun)
            #Attach to IDE controller
            #Find the IDE controller for the vm.
            vms = self._conn.MSVM_ComputerSystem(ElementName=vm_name)
            vm = vms[0]
            vmsettings = vm.associators(
                wmi_result_class='Msvm_VirtualSystemSettingData')
            rasds = vmsettings[0].associators(
                wmi_result_class='MSVM_ResourceAllocationSettingData')
            ctrller = [r for r in rasds
                if r.ResourceSubType == 'Microsoft Emulated IDE Controller'
                and r.Address == "0"]
            #Attaching to the same slot as the VHD disk file
            self._attach_volume_to_controller(ctrller, 0, mounted_disk, vm)
        except Exception as exn:
            LOG.exception(_('Attach boot from volume failed: %s'), exn)
            self._volutils.logout_storage_target(self._conn_wmi, target_iqn)
            raise vmutils.HyperVException(
                _('Unable to attach boot volume to instance %s')
                    % vm_name)

    def volume_in_mapping(self, mount_device, block_device_info):
        return self._volutils.volume_in_mapping(mount_device,
            block_device_info)

    def attach_volume(self, connection_info, instance_name, mountpoint):
        """Attach a volume to the SCSI controller"""
        LOG.debug(_("Attach_volume: %(connection_info)s, %(instance_name)s,"
        " %(mountpoint)s") % locals())
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        self._volutils.login_storage_target(target_lun, target_iqn,
            target_portal)
        try:
            #Getting the mounted disk
            mounted_disk = self._get_mounted_disk_from_lun(target_iqn,
                target_lun)
            #Find the SCSI controller for the vm
            vms = self._conn.MSVM_ComputerSystem(ElementName=instance_name)
            vm = vms[0]
            vmsettings = vm.associators(
                wmi_result_class='Msvm_VirtualSystemSettingData')
            rasds = vmsettings[0].associators(
                wmi_result_class='MSVM_ResourceAllocationSettingData')
            ctrller = [r for r in rasds
                if r.ResourceSubType == 'Microsoft Synthetic SCSI Controller']
            self._attach_volume_to_controller(
                ctrller, self._get_free_controller_slot(ctrller[0]),
                    mounted_disk, vm)
        except Exception as exn:
            LOG.exception(_('Attach volume failed: %s'), exn)
            self._volutils.logout_storage_target(self._conn_wmi, target_iqn)
            raise vmutils.HyperVException(
                _('Unable to attach volume to instance %s')
                    % instance_name)

    def _attach_volume_to_controller(self, controller, address, mounted_disk,
        instance):
        """Attach a volume to a controller """
        #Find the default disk drive object for the vm and clone it.
        diskdflt = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                WHERE ResourceSubType LIKE 'Microsoft Physical Disk Drive'\
                AND InstanceID LIKE '%Default%'")[0]
        diskdrive = self._vmutils.clone_wmi_obj(self._conn,
                'Msvm_ResourceAllocationSettingData', diskdflt)
        diskdrive.Address = address
        diskdrive.Parent = controller[0].path_()
        diskdrive.HostResource = [mounted_disk[0].path_()]
        new_resources = self._vmutils.add_virt_resource(self._conn, diskdrive,
            instance)
        if new_resources is None:
            raise vmutils.HyperVException(_('Failed to add volume to VM %s') %
                instance)

    def _get_free_controller_slot(self, scsi_controller):
        #Getting volumes mounted in the SCSI controller
        volumes = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                WHERE ResourceSubType LIKE 'Microsoft Physical Disk Drive'\
                AND Parent = '" + scsi_controller.path_() + "'")
        #Slots starts from 0, so the lenght of the disks gives us the free slot
        return len(volumes)

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Dettach a volume to the SCSI controller"""
        LOG.debug(_("Detach_volume: %(connection_info)s, %(instance_name)s,"
        " %(mountpoint)s") % locals())
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        #Getting the mounted disk
        mounted_disk = self._get_mounted_disk_from_lun(target_iqn, target_lun)
        physical_list = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                WHERE ResourceSubType LIKE 'Microsoft Physical Disk Drive'")
        physical_disk = 0
        for phydisk in physical_list:
            host_resource_list = phydisk.HostResource
            if host_resource_list is None:
                continue
            host_resource = str(host_resource_list[0].lower())
            mounted_disk_path = str(mounted_disk[0].path_().lower())
            LOG.debug(_("Mounted disk to detach is: %s"), mounted_disk_path)
            LOG.debug(_("host_resource disk detached is: %s"), host_resource)
            if host_resource == mounted_disk_path:
                physical_disk = phydisk
        LOG.debug(_("Physical disk detached is: %s"), physical_disk)
        vms = self._conn.MSVM_ComputerSystem(ElementName=instance_name)
        vm = vms[0]
        remove_result = self._vmutils.remove_virt_resource(self._conn,
            physical_disk, vm)
        if remove_result is False:
            raise vmutils.HyperVException(
                _('Failed to remove volume from VM %s') %
                instance_name)
        #Sending logout
        self._volutils.logout_storage_target(self._conn_wmi, target_iqn)

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = self._get_iscsi_initiator()
            if not self._initiator:
                LOG.warn(_('Could not determine iscsi initiator name'),
                         instance=instance)
        return {
            'ip': FLAGS.my_ip,
            'initiator': self._initiator,
        }

    def _get_iscsi_initiator(self):
        return self._volutils.get_iscsi_initiator(self._conn_cimv2)

    def _get_mounted_disk_from_lun(self, target_iqn, target_lun):
        initiator_session = self._conn_wmi.query(
                "SELECT * FROM MSiSCSIInitiator_SessionClass \
                WHERE TargetName='" + target_iqn + "'")[0]
        devices = initiator_session.Devices
        device_number = None
        for device in devices:
            LOG.debug(_("device.InitiatorName: %s"), device.InitiatorName)
            LOG.debug(_("device.TargetName: %s"), device.TargetName)
            LOG.debug(_("device.ScsiPortNumber: %s"), device.ScsiPortNumber)
            LOG.debug(_("device.ScsiPathId: %s"), device.ScsiPathId)
            LOG.debug(_("device.ScsiTargetId): %s"), device.ScsiTargetId)
            LOG.debug(_("device.ScsiLun: %s"), device.ScsiLun)
            LOG.debug(_("device.DeviceInterfaceGuid :%s"),
                device.DeviceInterfaceGuid)
            LOG.debug(_("device.DeviceInterfaceName: %s"),
                device.DeviceInterfaceName)
            LOG.debug(_("device.LegacyName: %s"), device.LegacyName)
            LOG.debug(_("device.DeviceType: %s"), device.DeviceType)
            LOG.debug(_("device.DeviceNumber %s"), device.DeviceNumber)
            LOG.debug(_("device.PartitionNumber :%s"), device.PartitionNumber)
            scsi_lun = device.ScsiLun
            if scsi_lun == target_lun:
                device_number = device.DeviceNumber
        if device_number is None:
            raise vmutils.HyperVException(
                _('Unable to find a mounted disk for'
                    ' target_iqn: %s') % target_iqn)
        LOG.debug(_("Device number : %s"), device_number)
        LOG.debug(_("Target lun : %s"), target_lun)
        #Finding Mounted disk drive
        for i in range(1, self._attaching_volume_retry_count):
            mounted_disk = self._conn.query(
                "SELECT * FROM Msvm_DiskDrive WHERE DriveNumber=" +
                    str(device_number) + "")
            LOG.debug(_("Mounted disk is: %s"), mounted_disk)
            if len(mounted_disk) > 0:
                break
            self._time.sleep(self._wait_between_attach_retry)
        mounted_disk = self._conn.query(
                "SELECT * FROM Msvm_DiskDrive WHERE DriveNumber=" +
                    str(device_number) + "")
        LOG.debug(_("Mounted disk is: %s"), mounted_disk)
        if len(mounted_disk) == 0:
            raise vmutils.HyperVException(
                _('Unable to find a mounted disk for'
                    ' target_iqn: %s') % target_iqn)
        return mounted_disk

    def disconnect_volume(self, physical_drive_path):
        #Get the session_id of the ISCSI connection
        session_id = self._get_session_id_from_mounted_disk(
            physical_drive_path)
        #Logging out the target
        self._volutils.execute_log_out(session_id)

    def _get_session_id_from_mounted_disk(self, physical_drive_path):
        drive_number = self._get_drive_number_from_disk_path(
            physical_drive_path)
        LOG.debug(_("Drive number to disconnect is: %s"), drive_number)
        initiator_sessions = self._conn_wmi.query(
                "SELECT * FROM MSiSCSIInitiator_SessionClass")
        for initiator_session in initiator_sessions:
            devices = initiator_session.Devices
            for device in devices:
                deviceNumber = str(device.DeviceNumber)
                LOG.debug(_("DeviceNumber : %s"), deviceNumber)
                if deviceNumber == drive_number:
                    return initiator_session.SessionId

    def _get_drive_number_from_disk_path(self, disk_path):
        LOG.debug(_("Disk path to parse: %s"), disk_path)
        start_device_id = disk_path.find('"', disk_path.find('DeviceID'))
        LOG.debug(_("start_device_id: %s"), start_device_id)
        end_device_id = disk_path.find('"', start_device_id + 1)
        LOG.debug(_("end_device_id: %s"), end_device_id)
        deviceID = disk_path[start_device_id + 1:end_device_id]
        return deviceID[deviceID.find("\\") + 2:]

    def get_default_root_device(self):
        return self._default_root_device
