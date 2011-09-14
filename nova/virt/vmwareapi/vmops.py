# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
Class for VM tasks like spawn, snapshot, suspend, resume etc.
"""

import base64
import os
import time
import urllib
import urllib2
import uuid

from nova import context as nova_context
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.compute import power_state
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmware_images
from nova.virt.vmwareapi import network_utils

FLAGS = flags.FLAGS
flags.DEFINE_string('vmware_vif_driver',
                    'nova.virt.vmwareapi.vif.VMWareVlanBridgeDriver',
                    'The VMWare VIF driver to configure the VIFs.')

LOG = logging.getLogger("nova.virt.vmwareapi.vmops")

VMWARE_POWER_STATES = {
                   'poweredOff': power_state.SHUTDOWN,
                    'poweredOn': power_state.RUNNING,
                    'suspended': power_state.PAUSED}


class VMWareVMOps(object):
    """Management class for VM-related tasks."""

    def __init__(self, session):
        """Initializer."""
        self._session = session
        self._vif_driver = utils.import_object(FLAGS.vmware_vif_driver)

    def _wait_with_callback(self, instance_id, task, callback):
        """Waits for the task to finish and does a callback after."""
        ret = None
        try:
            ret = self._session._wait_for_task(instance_id, task)
        except Exception, excep:
            LOG.exception(excep)
        callback(ret)

    def list_instances(self):
        """Lists the VM instances that are registered with the ESX host."""
        LOG.debug(_("Getting list of instances"))
        vms = self._session._call_method(vim_util, "get_objects",
                     "VirtualMachine",
                     ["name", "runtime.connectionState"])
        lst_vm_names = []
        for vm in vms:
            vm_name = None
            conn_state = None
            for prop in vm.propSet:
                if prop.name == "name":
                    vm_name = prop.val
                elif prop.name == "runtime.connectionState":
                    conn_state = prop.val
            # Ignoring the oprhaned or inaccessible VMs
            if conn_state not in ["orphaned", "inaccessible"]:
                lst_vm_names.append(vm_name)
        LOG.debug(_("Got total of %s instances") % str(len(lst_vm_names)))
        return lst_vm_names

    def spawn(self, context, instance, network_info):
        """
        Creates a VM instance.

        Steps followed are:
        1. Create a VM with no disk and the specifics in the instance object
            like RAM size.
        2. Create a dummy vmdk of the size of the disk file that is to be
            uploaded. This is required just to create the metadata file.
        3. Delete the -flat.vmdk file created in the above step and retain
            the metadata .vmdk file.
        4. Upload the disk file.
        5. Attach the disk to the VM by reconfiguring the same.
        6. Power on the VM.
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref:
            raise exception.InstanceExists(name=instance.name)

        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()

        def _get_datastore_ref():
            """Get the datastore list and choose the first local storage."""
            data_stores = self._session._call_method(vim_util, "get_objects",
                        "Datastore", ["summary.type", "summary.name"])
            for elem in data_stores:
                ds_name = None
                ds_type = None
                for prop in elem.propSet:
                    if prop.name == "summary.type":
                        ds_type = prop.val
                    elif prop.name == "summary.name":
                        ds_name = prop.val
                # Local storage identifier
                if ds_type == "VMFS":
                    data_store_name = ds_name
                    return data_store_name

            if data_store_name is None:
                msg = _("Couldn't get a local Datastore reference")
                LOG.exception(msg)
                raise exception.Error(msg)

        data_store_name = _get_datastore_ref()

        def _get_image_properties():
            """
            Get the Size of the flat vmdk file that is there on the storage
            repository.
            """
            image_size, image_properties = \
                    vmware_images.get_vmdk_size_and_properties(context,
                                       instance.image_ref, instance)
            vmdk_file_size_in_kb = int(image_size) / 1024
            os_type = image_properties.get("vmware_ostype", "otherGuest")
            adapter_type = image_properties.get("vmware_adaptertype",
                                                "lsiLogic")
            return vmdk_file_size_in_kb, os_type, adapter_type

        vmdk_file_size_in_kb, os_type, adapter_type = _get_image_properties()

        def _get_vmfolder_and_res_pool_mors():
            """Get the Vm folder ref from the datacenter."""
            dc_objs = self._session._call_method(vim_util, "get_objects",
                                    "Datacenter", ["vmFolder"])
            # There is only one default datacenter in a standalone ESX host
            vm_folder_mor = dc_objs[0].propSet[0].val

            # Get the resource pool. Taking the first resource pool coming our
            # way. Assuming that is the default resource pool.
            res_pool_mor = self._session._call_method(vim_util, "get_objects",
                                    "ResourcePool")[0].obj
            return vm_folder_mor, res_pool_mor

        vm_folder_mor, res_pool_mor = _get_vmfolder_and_res_pool_mors()

        def _check_if_network_bridge_exists(network_name):
            network_ref = \
                network_utils.get_network_with_the_name(self._session,
                                                        network_name)
            if network_ref is None:
                raise exception.NetworkNotFoundForBridge(bridge=network_name)
            return network_ref

        def _get_vif_infos():
            vif_infos = []
            for (network, mapping) in network_info:
                mac_address = mapping['mac']
                network_name = network['bridge']
                if mapping.get('should_create_vlan'):
                    network_ref = self._vif_driver.ensure_vlan_bridge(
                                                        self._session, network)
                else:
                    network_ref = _check_if_network_bridge_exists(network_name)
                vif_infos.append({'network_name': network_name,
                                  'mac_address': mac_address,
                                  'network_ref': network_ref,
                                 })
            return vif_infos

        vif_infos = _get_vif_infos()

        # Get the create vm config spec
        config_spec = vm_util.get_vm_create_spec(
                            client_factory, instance,
                            data_store_name, vif_infos, os_type)

        def _execute_create_vm():
            """Create VM on ESX host."""
            LOG.debug(_("Creating VM with the name %s on the ESX  host") %
                      instance.name)
            # Create the VM on the ESX host
            vm_create_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "CreateVM_Task", vm_folder_mor,
                                    config=config_spec, pool=res_pool_mor)
            self._session._wait_for_task(instance.id, vm_create_task)

            LOG.debug(_("Created VM with the name %s on the ESX  host") %
                      instance.name)

        _execute_create_vm()

        # Set the machine.id parameter of the instance to inject
        # the NIC configuration inside the VM
        if FLAGS.flat_injected:
            self._set_machine_id(client_factory, instance, network_info)

        # Naming the VM files in correspondence with the VM instance name
        # The flat vmdk file name
        flat_uploaded_vmdk_name = "%s/%s-flat.vmdk" % (instance.name,
                                                       instance.name)
        # The vmdk meta-data file
        uploaded_vmdk_name = "%s/%s.vmdk" % (instance.name, instance.name)
        flat_uploaded_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                            flat_uploaded_vmdk_name)
        uploaded_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                            uploaded_vmdk_name)

        def _create_virtual_disk():
            """Create a virtual disk of the size of flat vmdk file."""
            # Create a Virtual Disk of the size of the flat vmdk file. This is
            # done just to generate the meta-data file whose specifics
            # depend on the size of the disk, thin/thick provisioning and the
            # storage adapter type.
            # Here we assume thick provisioning and lsiLogic for the adapter
            # type
            LOG.debug(_("Creating Virtual Disk of size  "
                      "%(vmdk_file_size_in_kb)s KB and adapter type  "
                      "%(adapter_type)s on the ESX host local store"
                      " %(data_store_name)s") %
                       {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                        "adapter_type": adapter_type,
                        "data_store_name": data_store_name})
            vmdk_create_spec = vm_util.get_vmdk_create_spec(client_factory,
                                    vmdk_file_size_in_kb, adapter_type)
            vmdk_create_task = self._session._call_method(
                self._session._get_vim(),
                "CreateVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=uploaded_vmdk_path,
                datacenter=self._get_datacenter_name_and_ref()[0],
                spec=vmdk_create_spec)
            self._session._wait_for_task(instance.id, vmdk_create_task)
            LOG.debug(_("Created Virtual Disk of size %(vmdk_file_size_in_kb)s"
                        " KB on the ESX host local store "
                        "%(data_store_name)s") %
                        {"vmdk_file_size_in_kb": vmdk_file_size_in_kb,
                         "data_store_name": data_store_name})

        _create_virtual_disk()

        def _delete_disk_file():
            LOG.debug(_("Deleting the file %(flat_uploaded_vmdk_path)s "
                        "on the ESX host local"
                        "store %(data_store_name)s") %
                        {"flat_uploaded_vmdk_path": flat_uploaded_vmdk_path,
                         "data_store_name": data_store_name})
            # Delete the -flat.vmdk file created. .vmdk file is retained.
            vmdk_delete_task = self._session._call_method(
                        self._session._get_vim(),
                        "DeleteDatastoreFile_Task",
                        service_content.fileManager,
                        name=flat_uploaded_vmdk_path)
            self._session._wait_for_task(instance.id, vmdk_delete_task)
            LOG.debug(_("Deleted the file %(flat_uploaded_vmdk_path)s on the "
                        "ESX host local store %(data_store_name)s") %
                        {"flat_uploaded_vmdk_path": flat_uploaded_vmdk_path,
                         "data_store_name": data_store_name})

        _delete_disk_file()

        cookies = self._session._get_vim().client.options.transport.cookiejar

        def _fetch_image_on_esx_datastore():
            """Fetch image from Glance to ESX datastore."""
            LOG.debug(_("Downloading image file data %(image_ref)s to the ESX "
                        "data store %(data_store_name)s") %
                        ({'image_ref': instance.image_ref,
                          'data_store_name': data_store_name}))
            # Upload the -flat.vmdk file whose meta-data file we just created
            # above
            vmware_images.fetch_image(
                context,
                instance.image_ref,
                instance,
                host=self._session._host_ip,
                data_center_name=self._get_datacenter_name_and_ref()[1],
                datastore_name=data_store_name,
                cookies=cookies,
                file_path=flat_uploaded_vmdk_name)
            LOG.debug(_("Downloaded image file data %(image_ref)s to the ESX "
                        "data store %(data_store_name)s") %
                        ({'image_ref': instance.image_ref,
                         'data_store_name': data_store_name}))
        _fetch_image_on_esx_datastore()

        vm_ref = self._get_vm_ref_from_the_name(instance.name)

        def _attach_vmdk_to_the_vm():
            """
            Attach the vmdk uploaded to the VM. VM reconfigure is done
            to do so.
            """
            vmdk_attach_config_spec = vm_util.get_vmdk_attach_config_spec(
                                client_factory,
                                vmdk_file_size_in_kb, uploaded_vmdk_path,
                                adapter_type)
            LOG.debug(_("Reconfiguring VM instance %s to attach the image "
                      "disk") % instance.name)
            reconfig_task = self._session._call_method(
                               self._session._get_vim(),
                               "ReconfigVM_Task", vm_ref,
                               spec=vmdk_attach_config_spec)
            self._session._wait_for_task(instance.id, reconfig_task)
            LOG.debug(_("Reconfigured VM instance %s to attach the image "
                      "disk") % instance.name)

        _attach_vmdk_to_the_vm()

        def _power_on_vm():
            """Power on the VM."""
            LOG.debug(_("Powering on the VM instance %s") % instance.name)
            # Power On the VM
            power_on_task = self._session._call_method(
                               self._session._get_vim(),
                               "PowerOnVM_Task", vm_ref)
            self._session._wait_for_task(instance.id, power_on_task)
            LOG.debug(_("Powered on the VM instance %s") % instance.name)
        _power_on_vm()

    def snapshot(self, context, instance, snapshot_name):
        """
        Create snapshot from a running VM instance.
        Steps followed are:
        1. Get the name of the vmdk file which the VM points to right now.
            Can be a chain of snapshots, so we need to know the last in the
            chain.
        2. Create the snapshot. A new vmdk is created which the VM points to
            now. The earlier vmdk becomes read-only.
        3. Call CopyVirtualDisk which coalesces the disk chain to form a single
            vmdk, rather a .vmdk metadata file and a -flat.vmdk disk data file.
        4. Now upload the -flat.vmdk file to the image store.
        5. Delete the coalesced .vmdk and -flat.vmdk created.
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)

        client_factory = self._session._get_vim().client.factory
        service_content = self._session._get_vim().get_service_content()

        def _get_vm_and_vmdk_attribs():
            # Get the vmdk file name that the VM is pointing to
            hardware_devices = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "config.hardware.device")
            vmdk_file_path_before_snapshot, adapter_type = \
                vm_util.get_vmdk_file_path_and_adapter_type(client_factory,
                                                            hardware_devices)
            datastore_name = vm_util.split_datastore_path(
                                      vmdk_file_path_before_snapshot)[0]
            os_type = self._session._call_method(vim_util,
                        "get_dynamic_property", vm_ref,
                        "VirtualMachine", "summary.config.guestId")
            return (vmdk_file_path_before_snapshot, adapter_type,
                    datastore_name, os_type)

        vmdk_file_path_before_snapshot, adapter_type, datastore_name,\
            os_type = _get_vm_and_vmdk_attribs()

        def _create_vm_snapshot():
            # Create a snapshot of the VM
            LOG.debug(_("Creating Snapshot of the VM instance %s ") %
                        instance.name)
            snapshot_task = self._session._call_method(
                        self._session._get_vim(),
                        "CreateSnapshot_Task", vm_ref,
                        name="%s-snapshot" % instance.name,
                        description="Taking Snapshot of the VM",
                        memory=True,
                        quiesce=True)
            self._session._wait_for_task(instance.id, snapshot_task)
            LOG.debug(_("Created Snapshot of the VM instance %s ") %
                      instance.name)

        _create_vm_snapshot()

        def _check_if_tmp_folder_exists():
            # Copy the contents of the VM that were there just before the
            # snapshot was taken
            ds_ref_ret = vim_util.get_dynamic_property(
                                    self._session._get_vim(),
                                    vm_ref,
                                    "VirtualMachine",
                                    "datastore")
            if not ds_ref_ret:
                raise exception.DatastoreNotFound()
            ds_ref = ds_ref_ret.ManagedObjectReference[0]
            ds_browser = vim_util.get_dynamic_property(
                                       self._session._get_vim(),
                                       ds_ref,
                                       "Datastore",
                                       "browser")
            # Check if the vmware-tmp folder exists or not. If not, create one
            tmp_folder_path = vm_util.build_datastore_path(datastore_name,
                                                           "vmware-tmp")
            if not self._path_exists(ds_browser, tmp_folder_path):
                self._mkdir(vm_util.build_datastore_path(datastore_name,
                                                         "vmware-tmp"))

        _check_if_tmp_folder_exists()

        # Generate a random vmdk file name to which the coalesced vmdk content
        # will be copied to. A random name is chosen so that we don't have
        # name clashes.
        random_name = str(uuid.uuid4())
        dest_vmdk_file_location = vm_util.build_datastore_path(datastore_name,
                   "vmware-tmp/%s.vmdk" % random_name)
        dc_ref = self._get_datacenter_name_and_ref()[0]

        def _copy_vmdk_content():
            # Copy the contents of the disk ( or disks, if there were snapshots
            # done earlier) to a temporary vmdk file.
            copy_spec = vm_util.get_copy_virtual_disk_spec(client_factory,
                                                            adapter_type)
            LOG.debug(_("Copying disk data before snapshot of the VM "
                        " instance %s") % instance.name)
            copy_disk_task = self._session._call_method(
                self._session._get_vim(),
                "CopyVirtualDisk_Task",
                service_content.virtualDiskManager,
                sourceName=vmdk_file_path_before_snapshot,
                sourceDatacenter=dc_ref,
                destName=dest_vmdk_file_location,
                destDatacenter=dc_ref,
                destSpec=copy_spec,
                force=False)
            self._session._wait_for_task(instance.id, copy_disk_task)
            LOG.debug(_("Copied disk data before snapshot of the VM "
                        "instance %s") % instance.name)

        _copy_vmdk_content()

        cookies = self._session._get_vim().client.options.transport.cookiejar

        def _upload_vmdk_to_image_repository():
            # Upload the contents of -flat.vmdk file which has the disk data.
            LOG.debug(_("Uploading image %s") % snapshot_name)
            vmware_images.upload_image(
                context,
                snapshot_name,
                instance,
                os_type=os_type,
                adapter_type=adapter_type,
                image_version=1,
                host=self._session._host_ip,
                data_center_name=self._get_datacenter_name_and_ref()[1],
                datastore_name=datastore_name,
                cookies=cookies,
                file_path="vmware-tmp/%s-flat.vmdk" % random_name)
            LOG.debug(_("Uploaded image %s") % snapshot_name)

        _upload_vmdk_to_image_repository()

        def _clean_temp_data():
            """
            Delete temporary vmdk files generated in image handling
            operations.
            """
            # Delete the temporary vmdk created above.
            LOG.debug(_("Deleting temporary vmdk file %s")
                        % dest_vmdk_file_location)
            remove_disk_task = self._session._call_method(
                self._session._get_vim(),
                "DeleteVirtualDisk_Task",
                service_content.virtualDiskManager,
                name=dest_vmdk_file_location,
                datacenter=dc_ref)
            self._session._wait_for_task(instance.id, remove_disk_task)
            LOG.debug(_("Deleted temporary vmdk file %s")
                        % dest_vmdk_file_location)

        _clean_temp_data()

    def reboot(self, instance, network_info):
        """Reboot a VM instance."""
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)

        self.plug_vifs(instance, network_info)

        lst_properties = ["summary.guest.toolsStatus", "runtime.powerState",
                          "summary.guest.toolsRunningStatus"]
        props = self._session._call_method(vim_util, "get_object_properties",
                           None, vm_ref, "VirtualMachine",
                           lst_properties)
        pwr_state = None
        tools_status = None
        tools_running_status = False
        for elem in props:
            for prop in elem.propSet:
                if prop.name == "runtime.powerState":
                    pwr_state = prop.val
                elif prop.name == "summary.guest.toolsStatus":
                    tools_status = prop.val
                elif prop.name == "summary.guest.toolsRunningStatus":
                    tools_running_status = prop.val

        # Raise an exception if the VM is not powered On.
        if pwr_state not in ["poweredOn"]:
            reason = _("instance is not powered on")
            raise exception.InstanceRebootFailure(reason=reason)

        # If latest vmware tools are installed in the VM, and that the tools
        # are running, then only do a guest reboot. Otherwise do a hard reset.
        if (tools_status == "toolsOk" and
                tools_running_status == "guestToolsRunning"):
            LOG.debug(_("Rebooting guest OS of VM %s") % instance.name)
            self._session._call_method(self._session._get_vim(), "RebootGuest",
                                       vm_ref)
            LOG.debug(_("Rebooted guest OS of VM %s") % instance.name)
        else:
            LOG.debug(_("Doing hard reboot of VM %s") % instance.name)
            reset_task = self._session._call_method(self._session._get_vim(),
                                                    "ResetVM_Task", vm_ref)
            self._session._wait_for_task(instance.id, reset_task)
            LOG.debug(_("Did hard reboot of VM %s") % instance.name)

    def destroy(self, instance, network_info):
        """
        Destroy a VM instance. Steps followed are:
        1. Power off the VM, if it is in poweredOn state.
        2. Un-register a VM.
        3. Delete the contents of the folder holding the VM related data.
        """
        try:
            vm_ref = self._get_vm_ref_from_the_name(instance.name)
            if vm_ref is None:
                LOG.debug(_("instance - %s not present") % instance.name)
                return
            lst_properties = ["config.files.vmPathName", "runtime.powerState"]
            props = self._session._call_method(vim_util,
                        "get_object_properties",
                        None, vm_ref, "VirtualMachine", lst_properties)
            pwr_state = None
            for elem in props:
                vm_config_pathname = None
                for prop in elem.propSet:
                    if prop.name == "runtime.powerState":
                        pwr_state = prop.val
                    elif prop.name == "config.files.vmPathName":
                        vm_config_pathname = prop.val
            if vm_config_pathname:
                datastore_name, vmx_file_path = \
                            vm_util.split_datastore_path(vm_config_pathname)
            # Power off the VM if it is in PoweredOn state.
            if pwr_state == "poweredOn":
                LOG.debug(_("Powering off the VM %s") % instance.name)
                poweroff_task = self._session._call_method(
                       self._session._get_vim(),
                       "PowerOffVM_Task", vm_ref)
                self._session._wait_for_task(instance.id, poweroff_task)
                LOG.debug(_("Powered off the VM %s") % instance.name)

            # Un-register the VM
            try:
                LOG.debug(_("Unregistering the VM %s") % instance.name)
                self._session._call_method(self._session._get_vim(),
                        "UnregisterVM", vm_ref)
                LOG.debug(_("Unregistered the VM %s") % instance.name)
            except Exception, excep:
                LOG.warn(_("In vmwareapi:vmops:destroy, got this exception"
                           " while un-registering the VM: %s") % str(excep))

            self._unplug_vifs(instance, network_info)

            # Delete the folder holding the VM related content on
            # the datastore.
            try:
                dir_ds_compliant_path = vm_util.build_datastore_path(
                                 datastore_name,
                                 os.path.dirname(vmx_file_path))
                LOG.debug(_("Deleting contents of the VM %(name)s from "
                            "datastore %(datastore_name)s") %
                           ({'name': instance.name,
                             'datastore_name': datastore_name}))
                delete_task = self._session._call_method(
                    self._session._get_vim(),
                    "DeleteDatastoreFile_Task",
                    self._session._get_vim().get_service_content().fileManager,
                    name=dir_ds_compliant_path)
                self._session._wait_for_task(instance.id, delete_task)
                LOG.debug(_("Deleted contents of the VM %(name)s from "
                            "datastore %(datastore_name)s") %
                           ({'name': instance.name,
                             'datastore_name': datastore_name}))
            except Exception, excep:
                LOG.warn(_("In vmwareapi:vmops:destroy, "
                             "got this exception while deleting"
                             " the VM contents from the disk: %s")
                             % str(excep))
        except Exception, exc:
            LOG.exception(exc)

    def pause(self, instance, callback):
        """Pause a VM instance."""
        raise exception.ApiError("pause not supported for vmwareapi")

    def unpause(self, instance, callback):
        """Un-Pause a VM instance."""
        raise exception.ApiError("unpause not supported for vmwareapi")

    def suspend(self, instance, callback):
        """Suspend the specified instance."""
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)

        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        # Only PoweredOn VMs can be suspended.
        if pwr_state == "poweredOn":
            LOG.debug(_("Suspending the VM %s ") % instance.name)
            suspend_task = self._session._call_method(self._session._get_vim(),
                    "SuspendVM_Task", vm_ref)
            self._wait_with_callback(instance.id, suspend_task, callback)
            LOG.debug(_("Suspended the VM %s ") % instance.name)
        # Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            reason = _("instance is powered off and can not be suspended.")
            raise exception.InstanceSuspendFailure(reason=reason)

        LOG.debug(_("VM %s was already in suspended state. So returning "
                    "without doing anything") % instance.name)

    def resume(self, instance, callback):
        """Resume the specified instance."""
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)

        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.debug(_("Resuming the VM %s") % instance.name)
            suspend_task = self._session._call_method(
                                        self._session._get_vim(),
                                       "PowerOnVM_Task", vm_ref)
            self._wait_with_callback(instance.id, suspend_task, callback)
            LOG.debug(_("Resumed the VM %s ") % instance.name)
        else:
            reason = _("instance is not in a suspended state")
            raise exception.InstanceResumeFailure(reason=reason)

    def get_info(self, instance_name):
        """Return data about the VM instance."""
        vm_ref = self._get_vm_ref_from_the_name(instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)

        lst_properties = ["summary.config.numCpu",
                    "summary.config.memorySizeMB",
                    "runtime.powerState"]
        vm_props = self._session._call_method(vim_util,
                    "get_object_properties", None, vm_ref, "VirtualMachine",
                    lst_properties)
        max_mem = None
        pwr_state = None
        num_cpu = None
        for elem in vm_props:
            for prop in elem.propSet:
                if prop.name == "summary.config.numCpu":
                    num_cpu = int(prop.val)
                elif prop.name == "summary.config.memorySizeMB":
                    # In MB, but we want in KB
                    max_mem = int(prop.val) * 1024
                elif prop.name == "runtime.powerState":
                    pwr_state = VMWARE_POWER_STATES[prop.val]

        return {'state': pwr_state,
                'max_mem': max_mem,
                'mem': max_mem,
                'num_cpu': num_cpu,
                'cpu_time': 0}

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics."""
        raise exception.ApiError("get_diagnostics not implemented for "
                                 "vmwareapi")

    def get_console_output(self, instance):
        """Return snapshot of console."""
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)
        param_list = {"id": str(vm_ref)}
        base_url = "%s://%s/screen?%s" % (self._session._scheme,
                                         self._session._host_ip,
                                         urllib.urlencode(param_list))
        request = urllib2.Request(base_url)
        base64string = base64.encodestring(
                        '%s:%s' % (
                        self._session._host_username,
                        self._session._host_password)).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        result = urllib2.urlopen(request)
        if result.code == 200:
            return result.read()
        else:
            return ""

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console."""
        return 'http://fakeajaxconsole/fake_url'

    def _set_machine_id(self, client_factory, instance, network_info):
        """
        Set the machine id of the VM for guest tools to pick up and reconfigure
        the network interfaces.
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance.id)

        machine_id_str = ''
        for (network, info) in network_info:
            # TODO(vish): add support for dns2
            # TODO(sateesh): add support for injection of ipv6 configuration
            ip_v4 = ip_v6 = None
            if 'ips' in info and len(info['ips']) > 0:
                ip_v4 = info['ips'][0]
            if 'ip6s' in info and len(info['ip6s']) > 0:
                ip_v6 = info['ip6s'][0]
            if len(info['dns']) > 0:
                dns = info['dns'][0]
            else:
                dns = ''

            interface_str = "%s;%s;%s;%s;%s;%s" % \
                                            (info['mac'],
                                             ip_v4 and ip_v4['ip'] or '',
                                             ip_v4 and ip_v4['netmask'] or '',
                                             info['gateway'],
                                             info['broadcast'],
                                             dns)
            machine_id_str = machine_id_str + interface_str + '#'

        machine_id_change_spec = \
            vm_util.get_machine_id_change_spec(client_factory, machine_id_str)

        LOG.debug(_("Reconfiguring VM instance %(name)s to set the machine id "
                  "with ip - %(ip_addr)s") %
                  ({'name': instance.name,
                   'ip_addr': ip_v4['ip']}))
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=machine_id_change_spec)
        self._session._wait_for_task(instance.id, reconfig_task)
        LOG.debug(_("Reconfigured VM instance %(name)s to set the machine id "
                  "with ip - %(ip_addr)s") %
                  ({'name': instance.name,
                   'ip_addr': ip_v4['ip']}))

    def _get_datacenter_name_and_ref(self):
        """Get the datacenter name and the reference."""
        dc_obj = self._session._call_method(vim_util, "get_objects",
                "Datacenter", ["name"])
        return dc_obj[0].obj, dc_obj[0].propSet[0].val

    def _path_exists(self, ds_browser, ds_path):
        """Check if the path exists on the datastore."""
        search_task = self._session._call_method(self._session._get_vim(),
                                   "SearchDatastore_Task",
                                   ds_browser,
                                   datastorePath=ds_path)
        # Wait till the state changes from queued or running.
        # If an error state is returned, it means that the path doesn't exist.
        while True:
            task_info = self._session._call_method(vim_util,
                                       "get_dynamic_property",
                                       search_task, "Task", "info")
            if task_info.state in  ['queued', 'running']:
                time.sleep(2)
                continue
            break
        if task_info.state == "error":
            return False
        return True

    def _mkdir(self, ds_path):
        """
        Creates a directory at the path specified. If it is just "NAME",
        then a directory with this name is created at the topmost level of the
        DataStore.
        """
        LOG.debug(_("Creating directory with path %s") % ds_path)
        self._session._call_method(self._session._get_vim(), "MakeDirectory",
                    self._session._get_vim().get_service_content().fileManager,
                    name=ds_path, createParentDirectories=False)
        LOG.debug(_("Created directory with path %s") % ds_path)

    def _get_vm_ref_from_the_name(self, vm_name):
        """Get reference to the VM with the name specified."""
        vms = self._session._call_method(vim_util, "get_objects",
                    "VirtualMachine", ["name"])
        for vm in vms:
            if vm.propSet[0].val == vm_name:
                return vm.obj
        return None

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for (network, mapping) in network_info:
            self._vif_driver.plug(instance, network, mapping)

    def _unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for (network, mapping) in network_info:
            self._vif_driver.unplug(instance, network, mapping)
