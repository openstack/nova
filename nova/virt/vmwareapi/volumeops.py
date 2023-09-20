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
import uuid

from oslo_log import log as logging
from oslo_vmware import exceptions as oslo_vmw_exceptions
from oslo_vmware import vim_util as vutil

from nova.compute import power_state
import nova.conf
from nova import exception
from nova.i18n import _
from nova.virt import block_device
from nova.virt import driver
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import session
from nova.virt.vmwareapi import vm_util


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class VolumeMoRefProxy(session.StableMoRefProxy):
    def __init__(self, connection_info_data):
        volume_ref_value = connection_info_data.get('volume')
        ref = None
        if volume_ref_value:
            ref = vutil.get_moref(volume_ref_value, 'VirtualMachine')
        super(VolumeMoRefProxy, self).__init__(ref)
        self._connection_info_data = connection_info_data

    def fetch_moref(self, session):
        volume_id = self._connection_info_data.get('volume_id')
        if not volume_id:
            volume_id = self._connection_info_data.get('name')
        if volume_id:
            self.moref = vm_util._get_vm_ref_from_vm_uuid(session, volume_id)


class VMwareVolumeOps(object):
    """Management class for Volume-related tasks."""

    def __init__(self, session, cluster=None):
        self._session = session
        self._cluster = cluster

    def attach_disk_to_vm(self, vm_ref, instance,
                          adapter_type, disk_type, vmdk_path=None,
                          disk_size=None, linked_clone=False,
                          device_name=None, disk_io_limits=None,
                          volume_uuid=None, backing_uuid=None,
                          profile_id=None):
        """Attach disk to VM by reconfiguration.

        If volume_uuid and backing_uuid are given, also store the uuid of the
        volume's device in extraConfig in the same reconfigure request.
        """
        client_factory = self._session.vim.client.factory
        devices = vm_util.get_hardware_devices(self._session, vm_ref)
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                              client_factory,
                                                              devices,
                                                              adapter_type)

        vmdk_attach_config_spec = vm_util.get_vmdk_attach_config_spec(
                                    client_factory, disk_type, vmdk_path,
                                    disk_size, linked_clone, controller_key,
                                    unit_number, device_name, disk_io_limits,
                                    profile_id=profile_id)
        if controller_spec:
            vmdk_attach_config_spec.deviceChange.append(controller_spec)

        if volume_uuid and backing_uuid:
            LOG.debug("Adding volume details for %s to attach config spec.",
                      volume_uuid, instance=instance)
            self._add_volume_details_to_config_spec(vmdk_attach_config_spec,
                                                    volume_uuid, backing_uuid)

        LOG.debug("Reconfiguring VM instance %(vm_ref)s to attach "
                  "disk %(vmdk_path)s or device %(device_name)s with type "
                  "%(disk_type)s",
                  {'vm_ref': vutil.get_moref_value(vm_ref),
                   'vmdk_path': vmdk_path, 'device_name': device_name,
                   'disk_type': disk_type},
                  instance=instance)
        vm_util.reconfigure_vm(self._session, vm_ref, vmdk_attach_config_spec)
        LOG.debug("Reconfigured VM instance %(vm_ref)s to attach "
                  "disk %(vmdk_path)s or device %(device_name)s with type "
                  "%(disk_type)s",
                  {'vm_ref': vutil.get_moref_value(vm_ref),
                   'vmdk_path': vmdk_path, 'device_name': device_name,
                   'disk_type': disk_type},
                  instance=instance)

    def _add_volume_details_to_config_spec(self, config_spec, volume_uuid,
                                           device_uuid):
        """Store the UUID of the volume's device in extraConfig"""
        volume_option = 'volume-%s' % volume_uuid
        extra_opts = {volume_option: device_uuid}

        client_factory = self._session.vim.client.factory
        config_spec.extraConfig = vm_util.create_extra_config(client_factory,
                                                              extra_opts)

    def _get_volume_uuid(self, vm_ref, volume_uuid):
        prop = 'config.extraConfig["volume-%s"]' % volume_uuid
        opt_val = self._session._call_method(vutil,
                                             'get_object_property',
                                             vm_ref,
                                             prop)
        if opt_val is not None:
            return opt_val.value

    def detach_disk_from_vm(self, vm_ref, instance, device,
                            destroy_disk=False, volume_uuid=None):
        """Detach disk from VM by reconfiguration.

        If volume_uuid is given, also remove the key-value pair <volume_id,
        vmdk_uuid> from the instance's extraConfig in the same reconfigure
        request. Setting the value to an empty string will remove the key.
        """
        client_factory = self._session.vim.client.factory
        vmdk_detach_config_spec = vm_util.get_vmdk_detach_config_spec(
                                    client_factory, device, destroy_disk)

        if volume_uuid is not None:
            LOG.debug("Adding volume details for %s to detach config spec.",
                      volume_uuid, instance=instance)
            self._add_volume_details_to_config_spec(vmdk_detach_config_spec,
                                                    volume_uuid, '')

        disk_key = device.key
        LOG.debug("Reconfiguring VM instance %(vm_ref)s to detach "
                  "disk %(disk_key)s",
                  {'vm_ref': vutil.get_moref_value(vm_ref),
                   'disk_key': disk_key},
                  instance=instance)
        vm_util.reconfigure_vm(self._session, vm_ref, vmdk_detach_config_spec)
        LOG.debug("Reconfigured VM instance %(vm_ref)s to detach "
                  "disk %(disk_key)s",
                  {'vm_ref': vutil.get_moref_value(vm_ref),
                   'disk_key': disk_key},
                  instance=instance)

    def _iscsi_get_target(self, data):
        """Return the iSCSI Target given a volume info."""
        target_portal = data['target_portal']
        target_iqn = data['target_iqn']
        host_mor = vm_util.get_host_ref(self._session, self._cluster)

        lst_properties = ["config.storageDevice.hostBusAdapter",
                          "config.storageDevice.scsiTopology",
                          "config.storageDevice.scsiLun"]
        prop_dict = self._session._call_method(vutil,
                                               "get_object_properties_dict",
                                               host_mor,
                                               lst_properties)
        result = (None, None)
        hbas_ret = None
        scsi_topology = None
        scsi_lun_ret = None
        if prop_dict:
            hbas_ret = prop_dict.get('config.storageDevice.hostBusAdapter')
            scsi_topology = prop_dict.get('config.storageDevice.scsiTopology')
            scsi_lun_ret = prop_dict.get('config.storageDevice.scsiLun')

        # Meaning there are no host bus adapters on the host
        if hbas_ret is None:
            return result
        host_hbas = hbas_ret.HostHostBusAdapter
        if not host_hbas:
            return result
        for hba in host_hbas:
            if hba.__class__.__name__ == 'HostInternetScsiHba':
                hba_key = hba.key
                break
        else:
            return result

        if scsi_topology is None:
            return result
        host_adapters = scsi_topology.adapter
        if not host_adapters:
            return result
        scsi_lun_key = None
        for adapter in host_adapters:
            if adapter.adapter == hba_key:
                if not getattr(adapter, 'target', None):
                    return result
                for target in adapter.target:
                    if (getattr(target.transport, 'address', None) and
                        target.transport.address[0] == target_portal and
                            target.transport.iScsiName == target_iqn):
                        if not target.lun:
                            return result
                        for lun in target.lun:
                            if 'host.ScsiDisk' in lun.scsiLun:
                                scsi_lun_key = lun.scsiLun
                                break
                        break
                break

        if scsi_lun_key is None:
            return result

        if scsi_lun_ret is None:
            return result
        host_scsi_luns = scsi_lun_ret.ScsiLun
        if not host_scsi_luns:
            return result
        for scsi_lun in host_scsi_luns:
            if scsi_lun.key == scsi_lun_key:
                return (scsi_lun.deviceName, scsi_lun.uuid)

        return result

    def _iscsi_add_send_target_host(self, storage_system_mor, hba_device,
                                    target_portal):
        """Adds the iscsi host to send target host list."""
        client_factory = self._session.vim.client.factory
        send_tgt = client_factory.create('ns0:HostInternetScsiHbaSendTarget')
        (send_tgt.address, send_tgt.port) = target_portal.split(':')
        LOG.debug("Adding iSCSI host %s to send targets", send_tgt.address)
        self._session._call_method(
            self._session.vim, "AddInternetScsiSendTargets",
            storage_system_mor, iScsiHbaDevice=hba_device, targets=[send_tgt])

    def _iscsi_rescan_hba(self, target_portal):
        """Rescan the iSCSI HBA to discover iSCSI targets."""
        host_mor = vm_util.get_host_ref(self._session, self._cluster)
        storage_system_mor = self._session._call_method(
                                                vutil,
                                                "get_object_property",
                                                host_mor,
                                                "configManager.storageSystem")
        hbas_ret = self._session._call_method(
                                            vutil,
                                            "get_object_property",
                                            storage_system_mor,
                                            "storageDeviceInfo.hostBusAdapter")
        # Meaning there are no host bus adapters on the host
        if hbas_ret is None:
            return
        host_hbas = hbas_ret.HostHostBusAdapter
        if not host_hbas:
            return
        for hba in host_hbas:
            if hba.__class__.__name__ == 'HostInternetScsiHba':
                hba_device = hba.device
                if target_portal:
                    # Check if iscsi host is already in the send target host
                    # list
                    send_targets = getattr(hba, 'configuredSendTarget', [])
                    send_tgt_portals = ['%s:%s' % (s.address, s.port) for s in
                                        send_targets]
                    if target_portal not in send_tgt_portals:
                        self._iscsi_add_send_target_host(storage_system_mor,
                                                         hba_device,
                                                         target_portal)
                break
        else:
            return
        LOG.debug("Rescanning HBA %s", hba_device)
        self._session._call_method(self._session.vim,
                                   "RescanHba", storage_system_mor,
                                   hbaDevice=hba_device)
        LOG.debug("Rescanned HBA %s ", hba_device)

    def _iscsi_discover_target(self, data):
        """Get iSCSI target, rescanning the HBA if necessary."""
        target_portal = data['target_portal']
        target_iqn = data['target_iqn']
        LOG.debug("Discovering iSCSI target %(target_iqn)s from "
                  "%(target_portal)s.",
                  {'target_iqn': target_iqn, 'target_portal': target_portal})
        device_name, uuid = self._iscsi_get_target(data)
        if device_name:
            LOG.debug("Storage target found. No need to discover")
            return (device_name, uuid)

        # Rescan iSCSI HBA with iscsi target host
        self._iscsi_rescan_hba(target_portal)

        # Find iSCSI Target again
        device_name, uuid = self._iscsi_get_target(data)
        if device_name:
            LOG.debug("Discovered iSCSI target %(target_iqn)s from "
                      "%(target_portal)s.",
                      {'target_iqn': target_iqn,
                       'target_portal': target_portal})
        else:
            LOG.debug("Unable to discovered iSCSI target %(target_iqn)s "
                      "from %(target_portal)s.",
                      {'target_iqn': target_iqn,
                       'target_portal': target_portal})
        return (device_name, uuid)

    def _iscsi_get_host_iqn(self, instance):
        """Return the host iSCSI IQN."""
        try:
            host_mor = vm_util.get_host_ref_for_vm(self._session, instance)
        except exception.InstanceNotFound:
            host_mor = vm_util.get_host_ref(self._session, self._cluster)

        hbas_ret = self._session._call_method(
                                      vutil,
                                      "get_object_property",
                                      host_mor,
                                      "config.storageDevice.hostBusAdapter")

        # Meaning there are no host bus adapters on the host
        if hbas_ret is None:
            return
        host_hbas = hbas_ret.HostHostBusAdapter
        if not host_hbas:
            return
        for hba in host_hbas:
            if hba.__class__.__name__ == 'HostInternetScsiHba':
                return hba.iScsiName

    def _get_connection_capabilities(self):
        return ['vmware_service_instance_uuid:%s' %
                self._session.vim.service_content.about.instanceUuid]

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        try:
            vm_ref = vm_util.get_vm_ref(self._session, instance)
        except exception.InstanceNotFound:
            vm_ref = None
        iqn = self._iscsi_get_host_iqn(instance)
        connector = {'ip': CONF.vmware.host_ip,
                     'initiator': iqn,
                     'host': CONF.vmware.host_ip}
        if vm_ref:
            connector['instance'] = vutil.get_moref_value(vm_ref)

        connector['connection_capabilities'] = \
            self._get_connection_capabilities()

        return connector

    @staticmethod
    def _get_volume_ref(connection_info_data):
        """Get the volume moref from the "data" field in connection_info ."""
        return VolumeMoRefProxy(connection_info_data)

    def _get_vmdk_base_volume_device(self, volume_ref):
        # Get the vmdk file name that the VM is pointing to
        hardware_devices = vm_util.get_hardware_devices(self._session,
                                                        volume_ref)
        return vm_util.get_vmdk_volume_disk(hardware_devices)

    def _attach_volume_vmdk(self, connection_info, instance,
                            adapter_type=None):
        """Attach vmdk volume storage to VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        LOG.debug("_attach_volume_vmdk: %s", connection_info,
                  instance=instance)
        data = connection_info['data']
        volume_ref = self._get_volume_ref(data)

        # Get details required for adding disk device such as
        # adapter_type, disk_type
        vmdk = vm_util.get_vmdk_info(self._session, volume_ref)
        instance_root_vmdk_info = vm_util.get_vmdk_info(self._session, vm_ref)
        adapter_type = adapter_type or instance_root_vmdk_info.adapter_type

        # IDE does not support disk hotplug
        if adapter_type == constants.ADAPTER_TYPE_IDE:
            state = vm_util.get_vm_state(self._session, instance)
            if state != power_state.SHUTDOWN:
                raise exception.Invalid(_('%s does not support disk '
                                          'hotplug.') % adapter_type)

        # Attach the disk to virtual machine instance
        self.attach_disk_to_vm(vm_ref, instance, adapter_type, vmdk.disk_type,
                               vmdk_path=vmdk.path,
                               volume_uuid=data['volume_id'],
                               backing_uuid=vmdk.device.backing.uuid,
                               profile_id=data['profile_id'])

        LOG.debug("Attached VMDK: %s", connection_info, instance=instance)

    def _attach_volume_iscsi(self, connection_info, instance,
                             adapter_type=None):
        """Attach iscsi volume storage to VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Attach Volume to VM
        LOG.debug("_attach_volume_iscsi: %s", connection_info,
                  instance=instance)

        data = connection_info['data']

        # Discover iSCSI Target
        device_name = self._iscsi_discover_target(data)[0]
        if device_name is None:
            raise exception.StorageError(
                reason=_("Unable to find iSCSI Target"))
        if adapter_type is None:
            # Get the vmdk file name that the VM is pointing to
            hardware_devices = vm_util.get_hardware_devices(self._session,
                                                            vm_ref)
            adapter_type = vm_util.get_scsi_adapter_type(hardware_devices)

        self.attach_disk_to_vm(vm_ref, instance,
                               adapter_type, 'rdmp',
                               device_name=device_name,
                               profile_id=data.get('profile_id'))
        LOG.debug("Attached ISCSI: %s", connection_info, instance=instance)

    def _get_controller_key_and_unit(self, vm_ref, adapter_type):
        LOG.debug("_get_controller_key_and_unit vm: %(vm_ref)s, adapter: "
                  "%(adapter)s.",
                  {'vm_ref': vm_ref, 'adapter': adapter_type})
        client_factory = self._session.vim.client.factory
        devices = vm_util.get_hardware_devices(self._session, vm_ref)
        return vm_util.allocate_controller_key_and_unit_number(
            client_factory, devices, adapter_type)

    def _attach_fcd(self, instance, adapter_type, fcd_id,
                    ds_ref_val, profile_id=None):
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        (_, _, controller_spec) = self._get_controller_key_and_unit(
            vm_ref, adapter_type)

        if controller_spec:
            # No controller available to attach, create one first.
            config_spec = self._session.vim.client.factory.create(
                'ns0:VirtualMachineConfigSpec')
            config_spec.deviceChange = [controller_spec]
            vm_util.reconfigure_vm(self._session, vm_ref, config_spec)
            (_, _, controller_spec) = self._get_controller_key_and_unit(
                vm_ref, adapter_type)
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        virtual_dmgr = self._session.vim.service_content.virtualDiskManager
        cf = self._session.vim.client.factory
        disk_id = vm_util._create_fcd_id_obj(cf, fcd_id)
        fcd_obj = self._session.invoke_api(
            self._session.vim,
            'RetrieveVStorageObject',
            vstorage_mgr,
            id=disk_id,
            datastore=ds_ref_val)
        vmdk_path = fcd_obj.config.backing.filePath
        ds_ref = vutil.get_moref(ds_ref_val, "Datastore")
        uuid_hex = self._session.invoke_api(
            self._session.vim,
            'QueryVirtualDiskUuid',
            virtual_dmgr,
            name=vmdk_path,
            datacenter=ds_util.get_dc_info(self._session, ds_ref).ref)
        backing_uuid = str(uuid.UUID(uuid_hex.replace(' ', '')))

        volume_uuid = fcd_obj.config.name.replace('volume-', '')
        disk_type = fcd_obj.config.backing.provisioningType

        self.attach_disk_to_vm(vm_ref, instance, adapter_type, disk_type,
                               vmdk_path=vmdk_path,
                               volume_uuid=volume_uuid,
                               backing_uuid=backing_uuid,
                               profile_id=profile_id)

    def _attach_volume_fcd(self, connection_info, instance):
        """Attach fcd volume storage to VM instance."""
        LOG.debug("_attach_volume_fcd: %s", connection_info, instance=instance)
        data = connection_info['data']
        adapter_type = data['adapter_type']

        if adapter_type == constants.ADAPTER_TYPE_IDE:
            state = vm_util.get_vm_state(self._session, instance)
            if state != power_state.SHUTDOWN:
                raise exception.Invalid(_('%s does not support disk '
                                          'hotplug.') % adapter_type)

        self._attach_fcd(instance, adapter_type, data['id'],
                         data['ds_ref_val'],
                         data.get('profile_id'))
        LOG.debug("Attached fcd: %s", connection_info, instance=instance)

    def attach_volume(self, connection_info, instance, adapter_type=None):
        """Attach volume storage to VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug("Volume attach. Driver type: %s", driver_type,
                  instance=instance)
        if driver_type == constants.DISK_FORMAT_VMDK:
            self._attach_volume_vmdk(connection_info, instance, adapter_type)
        elif driver_type == constants.DISK_FORMAT_ISCSI:
            self._attach_volume_iscsi(connection_info, instance, adapter_type)
        elif driver_type == constants.DISK_FORMAT_FCD:
            self._attach_volume_fcd(connection_info, instance)
        else:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

    def _get_host_of_vm(self, vm_ref):
        """Get the ESX host of given VM."""
        return self._session._call_method(vutil, 'get_object_property',
                                          vm_ref, 'runtime').host

    def _get_res_pool_of_host(self, host):
        """Get the resource pool of given host's cluster."""
        # Get the compute resource, the host belongs to
        compute_res = self._session._call_method(vutil,
                                                 'get_object_property',
                                                 host,
                                                 'parent')
        # Get resource pool from the compute resource
        return self._session._call_method(vutil,
                                          'get_object_property',
                                          compute_res,
                                          'resourcePool')

    def _get_res_pool_of_vm(self, vm_ref):
        """Get resource pool to which the VM belongs."""
        # Get the host, the VM belongs to
        host = self._get_host_of_vm(vm_ref)
        # Get the resource pool of host's cluster.
        return self._get_res_pool_of_host(host)

    def _consolidate_vmdk_volume(self, instance, vm_ref, device, volume_ref,
                                 adapter_type=None, disk_type=None,
                                 profile_id=None):
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

        original_device = self._get_vmdk_base_volume_device(volume_ref)

        original_device_path = original_device.backing.fileName
        current_device_path = device.backing.fileName

        if original_device_path == current_device_path:
            # The volume is not moved from its original location.
            # No consolidation is required.
            LOG.debug("The volume has not been displaced from "
                      "its original location: %s. No consolidation "
                      "needed.", current_device_path)
            return

        # The volume has been moved from its original location.
        # Need to consolidate the VMDK files.
        LOG.info("The volume's backing has been relocated to %s. Need to "
                 "consolidate backing disk file.", current_device_path)

        # Pick the host and resource pool on which the instance resides.
        # Move the volume to the datastore where the new VMDK file is present.
        host = self._get_host_of_vm(vm_ref)
        res_pool = self._get_res_pool_of_host(host)
        datastore = device.backing.datastore
        detached = False
        LOG.debug("Relocating volume's backing: %(backing)s to resource "
                  "pool: %(rp)s, datastore: %(ds)s, host: %(host)s.",
                  {'backing': vutil.get_moref_value(volume_ref),
                   'rp': vutil.get_moref_value(res_pool),
                   'ds': vutil.get_moref_value(datastore),
                   'host': vutil.get_moref_value(host)})
        try:
            vm_util.relocate_vm(self._session, volume_ref, res_pool, datastore,
                                host)
        except oslo_vmw_exceptions.FileNotFoundException:
            # Volume's vmdk was moved; remove the device so that we can
            # relocate the volume.
            LOG.warning("Virtual disk: %s of volume's backing not found.",
                        original_device_path, exc_info=True)
            LOG.debug("Removing disk device of volume's backing and "
                      "reattempting relocate.")
            self.detach_disk_from_vm(volume_ref, instance, original_device)
            detached = True
            vm_util.relocate_vm(self._session, volume_ref, res_pool, datastore,
                                host)

        # Volume's backing is relocated now; detach the old vmdk if not done
        # already.
        if not detached:
            try:
                self.detach_disk_from_vm(volume_ref, instance,
                                         original_device, destroy_disk=True)
            except oslo_vmw_exceptions.FileNotFoundException:
                LOG.debug("Original volume backing %s is missing, no need "
                          "to detach it", original_device.backing.fileName)

        # Attach the current volume to the volume_ref
        self.attach_disk_to_vm(volume_ref, instance,
                               adapter_type, disk_type,
                               vmdk_path=current_device_path,
                               profile_id=profile_id)

    def _get_vmdk_backed_disk_device(self, vm_ref, connection_info_data):
        # Get the vmdk file name that the VM is pointing to
        hardware_devices = vm_util.get_hardware_devices(self._session, vm_ref)
        volume_uuid = connection_info_data['volume_id']

        # Try first the direct mapping
        device = vm_util.get_vmdk_backed_disk_device(hardware_devices,
                                                     volume_uuid)
        if device:
            return device

        # Fall back to the indirect mapping
        disk_uuid = self._get_volume_uuid(vm_ref, volume_uuid)
        device = vm_util.get_vmdk_backed_disk_device(hardware_devices,
                                                     disk_uuid)
        if not device:
            raise exception.DiskNotFound(message=_("Unable to find volume"))
        return device

    def _detach_volume_vmdk(self, connection_info, instance):
        """Detach volume storage to VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Detach Volume from VM
        LOG.debug("_detach_volume_vmdk: %s", connection_info,
                  instance=instance)
        data = connection_info['data']
        volume_ref = self._get_volume_ref(data)

        device = self._get_vmdk_backed_disk_device(vm_ref, data)

        hardware_devices = vm_util.get_hardware_devices(self._session, vm_ref)
        adapter_type = None
        for hw_device in hardware_devices:
            if hw_device.key == device.controllerKey:
                adapter_type = vm_util.CONTROLLER_TO_ADAPTER_TYPE.get(
                    hw_device.__class__.__name__)
                break

        # IDE does not support disk hotplug
        if adapter_type == constants.ADAPTER_TYPE_IDE:
            state = vm_util.get_vm_state(self._session, instance)
            if state != power_state.SHUTDOWN:
                raise exception.Invalid(_('%s does not support disk '
                                          'hotplug.') % adapter_type)

        disk_type = vm_util._get_device_disk_type(device)

        self._consolidate_vmdk_volume(instance, vm_ref, device, volume_ref,
                                      adapter_type=adapter_type,
                                      disk_type=disk_type,
                                      profile_id=data.get('profile_id'))

        self.detach_disk_from_vm(vm_ref, instance, device,
                                 volume_uuid=data['volume_id'])

        LOG.debug("Detached VMDK: %s", connection_info, instance=instance)

    def _detach_volume_iscsi(self, connection_info, instance):
        """Detach volume storage to VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # Detach Volume from VM
        LOG.debug("_detach_volume_iscsi: %s", connection_info,
                  instance=instance)
        data = connection_info['data']

        # Discover iSCSI Target
        device_name, uuid = self._iscsi_get_target(data)
        if device_name is None:
            raise exception.StorageError(
                reason=_("Unable to find iSCSI Target"))

        # Get the vmdk file name that the VM is pointing to
        hardware_devices = vm_util.get_hardware_devices(self._session, vm_ref)
        device = vm_util.get_rdm_disk(hardware_devices, uuid)
        if device is None:
            raise exception.DiskNotFound(message=_("Unable to find volume"))
        self.detach_disk_from_vm(vm_ref, instance, device, destroy_disk=True)
        LOG.debug("Detached ISCSI: %s", connection_info, instance=instance)

    def _detach_volume_fcd(self, connection_info, instance):
        """Detach fcd volume storage to VM instance."""
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        data = connection_info['data']
        adapter_type = data['adapter_type']

        if adapter_type == constants.ADAPTER_TYPE_IDE:
            state = vm_util.get_vm_state(self._session, instance)
            if state != power_state.SHUTDOWN:
                raise exception.Invalid(_('%s does not support disk '
                                          'hotplug.') % adapter_type)
        volume_uuid = block_device.get_volume_id(connection_info)
        # Copy the volume_id to data, as we need this for device search
        data['volume_id'] = volume_uuid
        device = self._get_vmdk_backed_disk_device(vm_ref, data)
        self.detach_disk_from_vm(vm_ref, instance, device,
                                 volume_uuid=volume_uuid)

    def detach_volume(self, connection_info, instance):
        """Detach volume storage to VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug("Volume detach. Driver type: %s", driver_type,
                  instance=instance)
        if driver_type == constants.DISK_FORMAT_VMDK:
            self._detach_volume_vmdk(connection_info, instance)
        elif driver_type == constants.DISK_FORMAT_ISCSI:
            self._detach_volume_iscsi(connection_info, instance)
        elif driver_type == constants.DISK_FORMAT_FCD:
            self._detach_volume_fcd(connection_info, instance)
        else:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

    def attach_root_volume(self, connection_info, instance,
                           datastore, adapter_type=None):
        """Attach a root volume to the VM instance."""
        driver_type = connection_info['driver_volume_type']
        LOG.debug("Root volume attach. Driver type: %s", driver_type,
                  instance=instance)
        # NOTE(jkulik): Upstream moves the volume to the instance DS here. This
        # would violate the differentiation between ephemeral and volume DS, so
        # we don't do that. This comment should help us detect upstream changes
        # to the function as merging should fail.
        self.attach_volume(connection_info, instance, adapter_type)

    def fixup_shadow_vms(self, instance, shadow_vms):
        """The function ensures that all volumes attached to a VM are also
        attached at the corresponding shadow vms.

        As the vcenter controls both VMs and volumes, and you can only move
        them together in a single migration operation between vcenters,
        Cinder cannot move the volumes indepenedently.
        It only can create the shadow-vms in the target vcenter.
        The backing then gets moved through the live-migration and needs to
        be reassociated with (attached to) the corresponding shadow-vms

        It handles the case that the shadow-vm is without backing (normal-case)
        But also that there is a pre-existing backing (e.g. we retry a failed
        migration)
        In the latter case, we discard the existing attachement of the
        shadow-vm, as the attached volume is the one with the more current data

        :param instance: The instance moved via a live-migration and to which
        the volumes are attached to
        :param shadow_vms: A mapping of devices with volumes to the
        connection_info.data information, most importantly holding the "volume"
        field, which is a managed-object reference to a shadow-vm
        """
        # This should sensibly moved out to cinder:
        # Cinder can delete the old shadow-vm, as soon as the attachment
        # for the vm prior the vmotion gets deleted
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        for device in vm_util.get_hardware_devices(self._session, vm_ref):
            class_name = device.__class__.__name__

            if class_name != "VirtualDisk":
                continue

            data = shadow_vms.get(device.key)
            if not data:
                continue

            try:
                current_device_path = device.backing.fileName
                volume = data["volume"]
                volume_ref = vutil.get_moref(volume, "VirtualMachine")
                original_device = self._get_vmdk_base_volume_device(volume_ref)
                if original_device:
                    original_device_path = original_device.backing.fileName
                    if original_device_path == current_device_path:
                        # Already attached
                        continue

                    # That should not happen
                    LOG.warning("Shadow-vm %s already has a disk"
                        " attached at %s replacing it with %s",
                        volume, original_device_path, current_device_path,
                        instance=instance
                        )
                    self.detach_disk_from_vm(volume_ref, instance,
                        original_device, destroy_disk=True)

                disk_type = vm_util._get_device_disk_type(device)
                self.attach_disk_to_vm(volume_ref,
                    instance,
                    constants.DEFAULT_ADAPTER_TYPE,
                    disk_type,
                    current_device_path,
                    profile_id=data.get("profile_id")
                    )
            except Exception:
                LOG.exception("Failed to attach volume {}. Device {}".format(
                    data["volume_id"],
                    device.key), instance=instance)

    def delete_shadow_vms(self, block_device_info, instance=None):
        # We need to delete the migrated shadow vms
        # (until we implement it in cinder)
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        if not block_device_mapping:
            return

        session = self._session
        deleted = []
        for disk in block_device_mapping:
            connection_info = disk["connection_info"]
            try:
                driver_type = connection_info['driver_volume_type']
                if driver_type == constants.DISK_FORMAT_FCD:
                    continue
                data = connection_info["data"]
                volume_ref = self._get_volume_ref(data["volume"])
                destroy_task = session._call_method(session.vim,
                                            "Destroy_Task",
                                            volume_ref)
                session._wait_for_task(destroy_task)
                deleted.append("{volume_id} ({volume})".format(**data))
            except oslo_vmw_exceptions.ManagedObjectNotFoundException:
                LOG.debug("Volume %s already deleted",
                        data.get("volume_id"), instance=instance)
            except Exception:
                LOG.exception("Failed to delete volume %s",
                        data.get("volume_id"), instance=instance)

        LOG.info("Deleted %s", deleted, instance=instance)

    def map_volumes_to_devices(self, instance, disk_infos):
        """Maps a connection_info.data to a device of the instance by its key
        :param instance: The instance the volumes are attached to
        :param disk_infos: An iterable over a dict containing at least
                           'volume_id'
        :returns: A dict {device_key: disk_info} mapping the passed disk_info
        dicts to a a device by the stored volume_id
        """
        remapped = {}
        vm_ref = vm_util.get_vm_ref(self._session, instance)
        # TODO(fwiesel) Create a function
        #  _get_vmdk_backed_disk_devices (plural)
        # so we do not have two calls for each device
        for disk_info in disk_infos:
            device = self._get_vmdk_backed_disk_device(vm_ref, disk_info)
            remapped[device.key] = disk_info
        return remapped
