# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
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

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import volume_util

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VMwareVolumeOps(object):
    """
    Management class for Volume-related tasks
    """

    def __init__(self, session, cluster=None, vc_support=False):
        self._session = session
        self._cluster = cluster
        self._vc_support = vc_support

    def attach_disk_to_vm(self, vm_ref, instance,
                          adapter_type, disk_type, vmdk_path=None,
                          disk_size=None, linked_clone=False,
                          controller_key=None, unit_number=None,
                          device_name=None):
        """
        Attach disk to VM by reconfiguration.
        """
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        vmdk_attach_config_spec = vm_util.get_vmdk_attach_config_spec(
                                    client_factory, adapter_type, disk_type,
                                    vmdk_path, disk_size, linked_clone,
                                    controller_key, unit_number, device_name)

        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to attach "
                    "disk %(vmdk_path)s or device %(device_name)s with type "
                    "%(disk_type)s"),
                  {'instance_name': instance_name, 'vmdk_path': vmdk_path,
                   'device_name': device_name, 'disk_type': disk_type})
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_attach_config_spec)
        self._session._wait_for_task(instance_uuid, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to attach "
                    "disk %(vmdk_path)s or device %(device_name)s with type "
                    "%(disk_type)s"),
                  {'instance_name': instance_name, 'vmdk_path': vmdk_path,
                   'device_name': device_name, 'disk_type': disk_type})

    def _update_volume_details(self, vm_ref, instance, volume_uuid):
        instance_name = instance['name']
        instance_uuid = instance['uuid']

        # Store the uuid of the volume_device
        hw_devices = self._session._call_method(vim_util,
                                                'get_dynamic_property',
                                                vm_ref, 'VirtualMachine',
                                                'config.hardware.device')
        device_uuid = vm_util.get_vmdk_backed_disk_uuid(hw_devices,
                                                        volume_uuid)
        volume_option = 'volume-%s' % volume_uuid
        extra_opts = {volume_option: device_uuid}

        client_factory = self._session._get_vim().client.factory
        extra_config_specs = vm_util.get_vm_extra_config_spec(
                                    client_factory, extra_opts)

        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=extra_config_specs)
        self._session._wait_for_task(instance_uuid, reconfig_task)

    def _get_volume_uuid(self, vm_ref, volume_uuid):
        volume_option = 'volume-%s' % volume_uuid
        extra_config = self._session._call_method(vim_util,
                                                  'get_dynamic_property',
                                                  vm_ref, 'VirtualMachine',
                                                  'config.extraConfig')
        if extra_config:
            options = extra_config.OptionValue
            for option in options:
                if option.key == volume_option:
                    return option.value

    def detach_disk_from_vm(self, vm_ref, instance, device):
        """
        Detach disk from VM by reconfiguration.
        """
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        client_factory = self._session._get_vim().client.factory
        vmdk_detach_config_spec = vm_util.get_vmdk_detach_config_spec(
                                    client_factory, device)
        disk_key = device.key
        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s"),
                  {'instance_name': instance_name, 'disk_key': disk_key})
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_detach_config_spec)
        self._session._wait_for_task(instance_uuid, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s"),
                  {'instance_name': instance_name, 'disk_key': disk_key})

    def discover_st(self, data):
        """Discover iSCSI targets."""
        target_portal = data['target_portal']
        target_iqn = data['target_iqn']
        LOG.debug(_("Discovering iSCSI target %(target_iqn)s from "
                    "%(target_portal)s."),
                  {'target_iqn': target_iqn, 'target_portal': target_portal})
        device_name, uuid = volume_util.find_st(self._session, data,
                                                self._cluster)
        if device_name:
            LOG.debug(_("Storage target found. No need to discover"))
            return (device_name, uuid)
        # Rescan iSCSI HBA
        volume_util.rescan_iscsi_hba(self._session, self._cluster)
        # Find iSCSI Target again
        device_name, uuid = volume_util.find_st(self._session, data,
                                                self._cluster)
        if device_name:
            LOG.debug(_("Discovered iSCSI target %(target_iqn)s from "
                        "%(target_portal)s."),
                      {'target_iqn': target_iqn,
                       'target_portal': target_portal})
        else:
            LOG.debug(_("Unable to discovered iSCSI target %(target_iqn)s "
                        "from %(target_portal)s."),
                      {'target_iqn': target_iqn,
                       'target_portal': target_portal})
        return (device_name, uuid)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        instance_name = instance['name']
        try:
            vm_ref = vm_util.get_vm_ref(self._session, instance)
        except exception.InstanceNotFound:
            vm_ref = None
        iqn = volume_util.get_host_iqn(self._session, self._cluster)
        connector = {'ip': CONF.vmware.host_ip,
                     'initiator': iqn,
                     'host': CONF.vmware.host_ip}
        if vm_ref:
            connector['instance'] = vm_ref.value
        return connector

    def _get_unit_number(self, mountpoint, unit_number):
        """Get a unit number for the device."""
        mount_unit = volume_util.mountpoint_to_number(mountpoint)
        # Figure out the correct unit number
        if unit_number < mount_unit:
            new_unit_number = mount_unit
        else:
            new_unit_number = unit_number + 1
        return new_unit_number

    def _get_volume_ref(self, volume_ref_name):
        """Get the volume moref from the ref name."""
        return vim.get_moref(volume_ref_name, 'VirtualMachine')

    def _get_vmdk_base_volume_device(self, volume_ref):
        # Get the vmdk file name that the VM is pointing to
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", volume_ref,
                        "VirtualMachine", "config.hardware.device")
        return vm_util.get_vmdk_volume_disk(hardware_devices)

    def _attach_volume_vmdk(self, connection_info, instance, mountpoint):
        """Attach vmdk volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        data = connection_info['data']

        # Get volume details from volume ref
        volume_ref = self._get_volume_ref(data['volume'])
        volume_device = self._get_vmdk_base_volume_device(volume_ref)
        volume_vmdk_path = volume_device.backing.fileName

        # Get details required for adding disk device such as
        # adapter_type, unit_number, controller_key
        hw_devices = self._session._call_method(vim_util,
                                                'get_dynamic_property',
                                                vm_ref, 'VirtualMachine',
                                                'config.hardware.device')
        (vmdk_file_path, controller_key, adapter_type, disk_type,
         unit_number) = vm_util.get_vmdk_path_and_adapter_type(hw_devices)

        unit_number = self._get_unit_number(mountpoint, unit_number)
        # Attach the disk to virtual machine instance
        volume_device = self.attach_disk_to_vm(vm_ref, instance, adapter_type,
                                               disk_type,
                                               vmdk_path=volume_vmdk_path,
                                               controller_key=controller_key,
                                               unit_number=unit_number)

        # Store the uuid of the volume_device
        self._update_volume_details(vm_ref, instance, data['volume_id'])

        LOG.info(_("Mountpoint %(mountpoint)s attached to "
                   "instance %(instance_name)s"),
                 {'mountpoint': mountpoint, 'instance_name': instance_name})

    def _attach_volume_iscsi(self, connection_info, instance, mountpoint):
        """Attach iscsi volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Attach Volume to VM
        LOG.debug(_("Attach_volume: %(connection_info)s, %(instance_name)s, "
                    "%(mountpoint)s"),
                  {'connection_info': connection_info,
                   'instance_name': instance_name,
                   'mountpoint': mountpoint})

        data = connection_info['data']

        # Discover iSCSI Target
        device_name, uuid = self.discover_st(data)
        if device_name is None:
            raise volume_util.StorageError(_("Unable to find iSCSI Target"))

        # Get the vmdk file name that the VM is pointing to
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
        vmdk_file_path, controller_key, adapter_type, disk_type, unit_number \
            = vm_util.get_vmdk_path_and_adapter_type(hardware_devices)

        unit_number = self._get_unit_number(mountpoint, unit_number)
        self.attach_disk_to_vm(vm_ref, instance,
                               adapter_type, 'rdmp',
                               controller_key=controller_key,
                               unit_number=unit_number,
                               device_name=device_name)
        LOG.info(_("Mountpoint %(mountpoint)s attached to "
                   "instance %(instance_name)s"),
                 {'mountpoint': mountpoint, 'instance_name': instance_name})

    def attach_volume(self, connection_info, instance, mountpoint):
        """Attach volume storage to VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug(_("Volume attach. Driver type: %s"), driver_type,
                instance=instance)
        if driver_type == 'vmdk':
            self._attach_volume_vmdk(connection_info, instance, mountpoint)
        elif driver_type == 'iscsi':
            self._attach_volume_iscsi(connection_info, instance, mountpoint)
        else:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

    def _relocate_vmdk_volume(self, volume_ref, res_pool, datastore):
        """Relocate the volume.

        The move type will be moveAllDiskBackingsAndAllowSharing.
        """
        client_factory = self._session._get_vim().client.factory
        spec = vm_util.relocate_vm_spec(client_factory,
                                        datastore=datastore)
        spec.pool = res_pool
        task = self._session._call_method(self._session._get_vim(),
                                          "RelocateVM_Task", volume_ref,
                                          spec=spec)
        self._session._wait_for_task(task.value, task)

    def _get_res_pool_of_vm(self, vm_ref):
        """Get resource pool to which the VM belongs."""
        # Get the host, the VM belongs to
        host = self._session._call_method(vim_util, 'get_dynamic_property',
                                          vm_ref, 'VirtualMachine',
                                          'runtime').host
        # Get the compute resource, the host belongs to
        compute_res = self._session._call_method(vim_util,
                                                 'get_dynamic_property',
                                                 host, 'HostSystem',
                                                 'parent')
        # Get resource pool from the compute resource
        return self._session._call_method(vim_util, 'get_dynamic_property',
                                          compute_res, compute_res._type,
                                          'resourcePool')

    def _consolidate_vmdk_volume(self, instance, vm_ref, device, volume_ref):
        """Consolidate volume backing VMDK files if needed.

        The volume's VMDK file attached to an instance can be moved by SDRS
        if enabled on the cluster.
        By this the VMDK files can get copied onto another datastore and the
        copy on this new location will be the latest version of the VMDK file.
        So at the time of detach, we need to consolidate the current backing
        VMDK file with the VMDK file in the new location.

        We need to ensure that the VMDK chain (snapshots) remains intact during
        the consolidation. SDRS retains the chain when it copies VMDK files
        over, so for consolidation we relocate the backing with move option
        as moveAllDiskBackingsAndAllowSharing and then delete the older version
        of the VMDK file attaching the new version VMDK file.

        In the case of a volume boot the we need to ensure that the volume
        is on the datastore of the instance.
        """

        # Consolidation only supported with VC driver
        if not self._vc_support:
            return

        original_device = self._get_vmdk_base_volume_device(volume_ref)

        original_device_path = original_device.backing.fileName
        current_device_path = device.backing.fileName

        if original_device_path == current_device_path:
            # The volume is not moved from its original location.
            # No consolidation is required.
            LOG.debug(_("The volume has not been displaced from "
                        "its original location: %s. No consolidation "
                        "needed."), current_device_path)
            return

        # The volume has been moved from its original location.
        # Need to consolidate the VMDK files.
        LOG.info(_("The volume's backing has been relocated to %s. Need to "
                   "consolidate backing disk file."), current_device_path)

        # Pick the resource pool on which the instance resides.
        # Move the volume to the datastore where the new VMDK file is present.
        res_pool = self._get_res_pool_of_vm(vm_ref)
        datastore = device.backing.datastore
        self._relocate_vmdk_volume(volume_ref, res_pool, datastore)

        # Delete the original disk from the volume_ref
        self.detach_disk_from_vm(volume_ref, instance, original_device)
        # Attach the current disk to the volume_ref
        # Get details required for adding disk device such as
        # adapter_type, unit_number, controller_key
        hw_devices = self._session._call_method(vim_util,
                                                'get_dynamic_property',
                                                volume_ref, 'VirtualMachine',
                                                'config.hardware.device')
        (vmdk_file_path, controller_key, adapter_type, disk_type,
         unit_number) = vm_util.get_vmdk_path_and_adapter_type(hw_devices)
        # Attach the curremt volumet to the volume_ref
        volume_device = self.attach_disk_to_vm(volume_ref, instance,
                                               adapter_type, disk_type,
                                               vmdk_path=current_device_path,
                                               controller_key=controller_key,
                                               unit_number=unit_number)

    def _get_vmdk_backed_disk_device(self, vm_ref, connection_info_data):
        # Get the vmdk file name that the VM is pointing to
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")

        # Get disk uuid
        disk_uuid = self._get_volume_uuid(vm_ref,
                                          connection_info_data['volume_id'])
        device = vm_util.get_vmdk_backed_disk_device(hardware_devices,
                                                     disk_uuid)
        if not device:
            raise volume_util.StorageError(_("Unable to find volume"))
        return device

    def _detach_volume_vmdk(self, connection_info, instance, mountpoint):
        """Detach volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Detach Volume from VM
        LOG.debug(_("Detach_volume: %(instance_name)s, %(mountpoint)s"),
                  {'mountpoint': mountpoint, 'instance_name': instance_name})
        data = connection_info['data']

        device = self._get_vmdk_backed_disk_device(vm_ref, data)

        # Get the volume ref
        volume_ref = self._get_volume_ref(data['volume'])
        self._consolidate_vmdk_volume(instance, vm_ref, device, volume_ref)

        self.detach_disk_from_vm(vm_ref, instance, device)
        LOG.info(_("Mountpoint %(mountpoint)s detached from "
                   "instance %(instance_name)s"),
                 {'mountpoint': mountpoint, 'instance_name': instance_name})

    def _detach_volume_iscsi(self, connection_info, instance, mountpoint):
        """Detach volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Detach Volume from VM
        LOG.debug(_("Detach_volume: %(instance_name)s, %(mountpoint)s"),
                  {'mountpoint': mountpoint, 'instance_name': instance_name})
        data = connection_info['data']

        # Discover iSCSI Target
        device_name, uuid = volume_util.find_st(self._session, data,
                                                self._cluster)
        if device_name is None:
            raise volume_util.StorageError(_("Unable to find iSCSI Target"))

        # Get the vmdk file name that the VM is pointing to
        hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
        device = vm_util.get_rdm_disk(hardware_devices, uuid)
        if device is None:
            raise volume_util.StorageError(_("Unable to find volume"))
        self.detach_disk_from_vm(vm_ref, instance, device)
        LOG.info(_("Mountpoint %(mountpoint)s detached from "
                   "instance %(instance_name)s"),
                 {'mountpoint': mountpoint, 'instance_name': instance_name})

    def detach_volume(self, connection_info, instance, mountpoint):
        """Detach volume storage to VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug(_("Volume detach. Driver type: %s"), driver_type,
                instance=instance)
        if driver_type == 'vmdk':
            self._detach_volume_vmdk(connection_info, instance, mountpoint)
        elif driver_type == 'iscsi':
            self._detach_volume_iscsi(connection_info, instance, mountpoint)
        else:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

    def attach_root_volume(self, connection_info, instance, mountpoint,
                           datastore):
        """Attach a root volume to the VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug(_("Root volume attach. Driver type: %s"), driver_type,
                  instance=instance)
        if driver_type == 'vmdk':
            vm_ref = vm_util.get_vm_ref(self._session, instance)
            data = connection_info['data']
            # Get the volume ref
            volume_ref = self._get_volume_ref(data['volume'])
            # Pick the resource pool on which the instance resides. Move the
            # volume to the datastore of the instance.
            res_pool = self._get_res_pool_of_vm(vm_ref)
            self._relocate_vmdk_volume(volume_ref, res_pool, datastore)

        self.attach_volume(connection_info, instance, mountpoint)
