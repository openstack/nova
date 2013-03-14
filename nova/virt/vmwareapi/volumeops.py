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
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import volume_util

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VMwareVolumeOps(object):
    """
    Management class for Volume-related tasks
    """

    def __init__(self, session, cluster=None):
        self._session = session
        self._cluster = cluster

    def attach_disk_to_vm(self, vm_ref, instance_name,
                          adapter_type, disk_type, vmdk_path=None,
                          disk_size=None, linked_clone=False,
                          controller_key=None, unit_number=None,
                          device_name=None):
        """
        Attach disk to VM by reconfiguration.
        """
        client_factory = self._session._get_vim().client.factory
        vmdk_attach_config_spec = vm_util.get_vmdk_attach_config_spec(
                                    client_factory, adapter_type, disk_type,
                                    vmdk_path, disk_size, linked_clone,
                                    controller_key, unit_number, device_name)

        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to attach "
                    "disk %(vmdk_path)s or device %(device_name)s with type "
                    "%(disk_type)s") % locals())
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_attach_config_spec)
        self._session._wait_for_task(instance_name, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to attach "
                    "disk %(vmdk_path)s or device %(device_name)s with type "
                    "%(disk_type)s") % locals())

    def detach_disk_from_vm(self, vm_ref, instance_name, device):
        """
        Detach disk from VM by reconfiguration.
        """
        client_factory = self._session._get_vim().client.factory
        vmdk_detach_config_spec = vm_util.get_vmdk_detach_config_spec(
                                    client_factory, device)
        disk_key = device.key
        LOG.debug(_("Reconfiguring VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s") % locals())
        reconfig_task = self._session._call_method(
                                        self._session._get_vim(),
                                        "ReconfigVM_Task", vm_ref,
                                        spec=vmdk_detach_config_spec)
        self._session._wait_for_task(instance_name, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(instance_name)s to detach "
                    "disk %(disk_key)s") % locals())

    def discover_st(self, data):
        """Discover iSCSI targets."""
        target_portal = data['target_portal']
        target_iqn = data['target_iqn']
        LOG.debug(_("Discovering iSCSI target %(target_iqn)s from "
                    "%(target_portal)s.") % locals())
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
                        "%(target_portal)s.") % locals())
        else:
            LOG.debug(_("Unable to discovered iSCSI target %(target_iqn)s "
                        "from %(target_portal)s.") % locals())
        return (device_name, uuid)

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        iqn = volume_util.get_host_iqn(self._session, self._cluster)
        return {
            'ip': CONF.vmwareapi_host_ip,
            'initiator': iqn,
            'host': CONF.vmwareapi_host_ip
        }

    def attach_volume(self, connection_info, instance, mountpoint):
        """Attach volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref_from_name(self._session, instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        # Attach Volume to VM
        LOG.debug(_("Attach_volume: %(connection_info)s, %(instance_name)s, "
                    "%(mountpoint)s") % locals())
        driver_type = connection_info['driver_volume_type']
        if driver_type not in ['iscsi']:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        data = connection_info['data']
        mount_unit = volume_util.mountpoint_to_number(mountpoint)

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
        # Figure out the correct unit number
        if unit_number < mount_unit:
            unit_number = mount_unit
        else:
            unit_number = unit_number + 1
        self.attach_disk_to_vm(vm_ref, instance_name,
                               adapter_type, disk_type="rdmp",
                               controller_key=controller_key,
                               unit_number=unit_number,
                               device_name=device_name)
        LOG.info(_("Mountpoint %(mountpoint)s attached to "
                   "instance %(instance_name)s") % locals())

    def detach_volume(self, connection_info, instance, mountpoint):
        """Detach volume storage to VM instance."""
        instance_name = instance['name']
        vm_ref = vm_util.get_vm_ref_from_name(self._session, instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        # Detach Volume from VM
        LOG.debug(_("Detach_volume: %(instance_name)s, %(mountpoint)s")
                    % locals())
        driver_type = connection_info['driver_volume_type']
        if driver_type not in ['iscsi']:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
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
        self.detach_disk_from_vm(vm_ref, instance_name, device)
        LOG.info(_("Mountpoint %(mountpoint)s detached from "
                   "instance %(instance_name)s") % locals())
