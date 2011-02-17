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

import logging
import os
import time
import uuid

from nova import db
from nova import context
from nova.compute import power_state

from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmware_images

LOG = logging.getLogger("nova.virt.vmwareapi.vmops")

VMWARE_POWER_STATES = {
                   'poweredOff': power_state.SHUTDOWN,
                    'poweredOn': power_state.RUNNING,
                    'suspended': power_state.PAUSED}


class VMWareVMOps(object):
    """
    Management class for VM-related tasks
    """

    def __init__(self, session):
        """
        Initializer
        """
        self._session = session

    def _wait_with_callback(self, instance_id, task, callback):
        """
        Waits for the task to finish and does a callback after
        """
        ret = None
        try:
            ret = self._session._wait_for_task(instance_id, task)
        except Exception, excep:
            LOG.exception(excep)
        callback(ret)

    def list_instances(self):
        """
        Lists the VM instances that are registered with the ESX host
        """
        LOG.debug("Getting list of instances")
        vms = self._session._call_method(vim_util, "get_objects",
                     "VirtualMachine",
                     ["name", "runtime.connectionState"])
        lst_vm_names = []
        for vm in vms:
            vm_name = None
            conn_state = None
            for prop in vm.PropSet:
                if prop.Name == "name":
                    vm_name = prop.Val
                elif prop.Name == "runtime.connectionState":
                    conn_state = prop.Val
            # Ignoring the oprhaned or inaccessible VMs
            if conn_state not in ["orphaned", "inaccessible"]:
                lst_vm_names.append(vm_name)
        LOG.debug("Got total of %s instances" % str(len(lst_vm_names)))
        return lst_vm_names

    def spawn(self, instance):
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
        6. Power on the VM
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref:
            raise Exception('Attempted to create a VM with a name %s, '
                'but that already exists on the host' % instance.name)
        bridge = db.network_get_by_instance(context.get_admin_context(),
                                            instance['id'])['bridge']
        #TODO: Shouldn't we consider any public network in case the network
        #name supplied isn't there
        network_ref = \
            self._get_network_with_the_name(bridge)
        if network_ref is None:
            raise Exception("Network with the name '%s' doesn't exist on "
                    "the ESX host" % bridge)

        #Get the Size of the flat vmdk file that is there on the storage
        #repository.
        image_size, image_properties = \
                vmware_images.get_vmdk_size_and_properties(instance.image_id,
                                                           instance)
        vmdk_file_size_in_kb = int(image_size) / 1024
        os_type = image_properties.get("vmware_ostype", "otherGuest")
        adapter_type = image_properties.get("vmware_adaptertype", "lsiLogic")

        # Get the datastore list and choose the first local storage
        data_stores = self._session._call_method(vim_util, "get_objects",
                    "Datastore", ["summary.type", "summary.name"])
        data_store_name = None
        for elem in data_stores:
            ds_name = None
            ds_type = None
            for prop in elem.PropSet:
                if prop.Name == "summary.type":
                    ds_type = prop.Val
                elif prop.Name == "summary.name":
                    ds_name = prop.Val
            #Local storage identifier
            if ds_type == "VMFS":
                data_store_name = ds_name
                break

        if data_store_name is None:
            msg = "Couldn't get a local Datastore reference"
            LOG.exception(msg)
            raise Exception(msg)

        config_spec = vm_util.get_vm_create_spec(instance, data_store_name,
                                bridge, os_type)

        #Get the Vm folder ref from the datacenter
        dc_objs = self._session._call_method(vim_util, "get_objects",
                                "Datacenter", ["vmFolder"])
        #There is only one default datacenter in a standalone ESX host
        vm_folder_ref = dc_objs[0].PropSet[0].Val

        #Get the resource pool. Taking the first resource pool coming our way.
        #Assuming that is the default resource pool.
        res_pool_mor = self._session._call_method(vim_util, "get_objects",
                                "ResourcePool")[0].Obj

        LOG.debug("Creating VM with the name %s on the ESX  host" %
                  instance.name)
        #Create the VM on the ESX host
        vm_create_task = self._session._call_method(self._session._get_vim(),
                                "CreateVM_Task", vm_folder_ref,
                                config=config_spec, pool=res_pool_mor)
        self._session._wait_for_task(instance.id, vm_create_task)

        LOG.debug("Created VM with the name %s on the ESX  host" %
                  instance.name)

        # Set the machine id for the VM for setting the IP
        self._set_machine_id(instance)

        #Naming the VM files in correspondence with the VM instance name

        # The flat vmdk file name
        flat_uploaded_vmdk_name = "%s/%s-flat.vmdk" % (instance.name,
                                                       instance.name)
        #The vmdk meta-data file
        uploaded_vmdk_name = "%s/%s.vmdk" % (instance.name, instance.name)
        flat_uploaded_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                            flat_uploaded_vmdk_name)
        uploaded_vmdk_path = vm_util.build_datastore_path(data_store_name,
                                            uploaded_vmdk_name)

        #Create a Virtual Disk of the size of the flat vmdk file. This is done
        #just created to generate the meta-data file whose specifics
        #depend on the size of the disk, thin/thick provisioning and the
        #storage adapter type.
        #Here we assume thick provisioning and lsiLogic for the adapter type
        LOG.debug("Creating Virtual Disk of size %s KB and adapter type %s on "
                  "the ESX host local store %s " %
                  (vmdk_file_size_in_kb, adapter_type, data_store_name))
        vmdk_create_spec = vm_util.get_vmdk_create_spec(vmdk_file_size_in_kb,
                                                        adapter_type)
        vmdk_create_task = self._session._call_method(self._session._get_vim(),
            "CreateVirtualDisk_Task",
            self._session._get_vim().get_service_content().VirtualDiskManager,
            name=uploaded_vmdk_path,
            datacenter=self._get_datacenter_name_and_ref()[0],
            spec=vmdk_create_spec)
        self._session._wait_for_task(instance.id, vmdk_create_task)
        LOG.debug("Created Virtual Disk of size %s KB on the ESX host local"
                  "store %s " % (vmdk_file_size_in_kb, data_store_name))

        LOG.debug("Deleting the file %s on the ESX host local"
                  "store %s " % (flat_uploaded_vmdk_path, data_store_name))
        #Delete the -flat.vmdk file created. .vmdk file is retained.
        vmdk_delete_task = self._session._call_method(self._session._get_vim(),
                    "DeleteDatastoreFile_Task",
                    self._session._get_vim().get_service_content().FileManager,
                    name=flat_uploaded_vmdk_path)
        self._session._wait_for_task(instance.id, vmdk_delete_task)
        LOG.debug("Deleted the file %s on the ESX host local"
                  "store %s " % (flat_uploaded_vmdk_path, data_store_name))

        LOG.debug("Downloading image file data %s to the ESX data store %s " %
                  (instance.image_id, data_store_name))
        # Upload the -flat.vmdk file whose meta-data file we just created above
        vmware_images.fetch_image(
                    instance.image_id,
                    instance,
                    host=self._session._host_ip,
                    data_center_name=self._get_datacenter_name_and_ref()[1],
                    datastore_name=data_store_name,
                    cookies=self._session._get_vim().proxy.binding.cookies,
                    file_path=flat_uploaded_vmdk_name)
        LOG.debug("Downloaded image file data %s to the ESX data store %s " %
                  (instance.image_id, data_store_name))

        #Attach the vmdk uploaded to the VM. VM reconfigure is done to do so.
        vmdk_attach_config_spec = vm_util.get_vmdk_attach_config_sepc(
                            vmdk_file_size_in_kb, uploaded_vmdk_path,
                            adapter_type)
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        LOG.debug("Reconfiguring VM instance %s to attach the image "
                  "disk" % instance.name)
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=vmdk_attach_config_spec)
        self._session._wait_for_task(instance.id, reconfig_task)
        LOG.debug("Reconfigured VM instance %s to attach the image "
                  "disk" % instance.name)

        LOG.debug("Powering on the VM instance %s " % instance.name)
        #Power On the VM
        power_on_task = self._session._call_method(self._session._get_vim(),
                           "PowerOnVM_Task", vm_ref)
        self._session._wait_for_task(instance.id, power_on_task)
        LOG.debug("Powered on the VM instance %s " % instance.name)

    def snapshot(self, instance, snapshot_name):
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
        5. Delete the coalesced .vmdk and -flat.vmdk created
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance.name)

        #Get the vmdk file name that the VM is pointing to
        hardware_devices = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "config.hardware.device")
        vmdk_file_path_before_snapshot, adapter_type = \
                vm_util.get_vmdk_file_path_and_adapter_type(hardware_devices)

        os_type = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "summary.config.guestId")
        #Create a snapshot of the VM
        LOG.debug("Creating Snapshot of the VM instance %s " % instance.name)
        snapshot_task = self._session._call_method(self._session._get_vim(),
                    "CreateSnapshot_Task", vm_ref,
                    name="%s-snapshot" % instance.name,
                    description="Taking Snapshot of the VM",
                    memory=True,
                    quiesce=True)
        self._session._wait_for_task(instance.id, snapshot_task)
        LOG.debug("Created Snapshot of the VM instance %s " % instance.name)

        datastore_name = vm_util.split_datastore_path(
                                  vmdk_file_path_before_snapshot)[0]
        #Copy the contents of the VM that were there just before the snapshot
        #was taken
        ds_ref = vim_util.get_dynamic_property(self._session._get_vim(),
                                      vm_ref,
                                      "VirtualMachine",
                                      "datastore").ManagedObjectReference[0]
        ds_browser = vim_util.get_dynamic_property(self._session._get_vim(),
                                       ds_ref,
                                       "Datastore",
                                       "browser")
        #Check if the vmware-tmp folder exists or not. If not, create one
        tmp_folder_path = vm_util.build_datastore_path(datastore_name,
                                                       "vmware-tmp")
        if not self._path_exists(ds_browser, tmp_folder_path):
            self._mkdir(vm_util.build_datastore_path(datastore_name,
                                                     "vmware-tmp"))

        copy_spec = vm_util.get_copy_virtual_disk_spec(adapter_type)

        #Generate a random vmdk file name to which the coalesced vmdk content
        #will be copied to. A random name is chosen so that we don't have
        #name clashes.
        random_name = str(uuid.uuid4())
        dest_vmdk_file_location = vm_util.build_datastore_path(datastore_name,
                   "vmware-tmp/%s.vmdk" % random_name)
        dc_ref = self._get_datacenter_name_and_ref()[0]

        #Copy the contents of the disk ( or disks, if there were snapshots
        #done earlier) to a temporary vmdk file.
        LOG.debug("Copying disk data before snapshot of the VM instance %s " %
                  instance.name)
        copy_disk_task = self._session._call_method(self._session._get_vim(),
            "CopyVirtualDisk_Task",
            self._session._get_vim().get_service_content().VirtualDiskManager,
            sourceName=vmdk_file_path_before_snapshot,
            sourceDatacenter=dc_ref,
            destName=dest_vmdk_file_location,
            destDatacenter=dc_ref,
            destSpec=copy_spec,
            force=False)
        self._session._wait_for_task(instance.id, copy_disk_task)
        LOG.debug("Copied disk data before snapshot of the VM instance %s " %
                  instance.name)

        #Upload the contents of -flat.vmdk file which has the disk data.
        LOG.debug("Uploading image %s" % snapshot_name)
        vmware_images.upload_image(
                    snapshot_name,
                    instance,
                    os_type=os_type,
                    adapter_type=adapter_type,
                    image_version=1,
                    host=self._session._host_ip,
                    data_center_name=self._get_datacenter_name_and_ref()[1],
                    datastore_name=datastore_name,
                    cookies=self._session._get_vim().proxy.binding.cookies,
                    file_path="vmware-tmp/%s-flat.vmdk" % random_name)
        LOG.debug("Uploaded image %s" % snapshot_name)

        #Delete the temporary vmdk created above.
        LOG.debug("Deleting temporary vmdk file %s" % dest_vmdk_file_location)
        remove_disk_task = self._session._call_method(self._session._get_vim(),
            "DeleteVirtualDisk_Task",
            self._session._get_vim().get_service_content().VirtualDiskManager,
             name=dest_vmdk_file_location,
            datacenter=dc_ref)
        self._session._wait_for_task(instance.id, remove_disk_task)
        LOG.debug("Deleted temporary vmdk file %s" % dest_vmdk_file_location)

    def reboot(self, instance):
        """
        Reboot a VM instance
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance.name)
        lst_properties = ["summary.guest.toolsStatus", "runtime.powerState"]
        props = self._session._call_method(vim_util, "get_object_properties",
                           None, vm_ref, "VirtualMachine",
                           lst_properties)
        for elem in props:
            pwr_state = None
            tools_status = None
            for prop in elem.PropSet:
                if prop.Name == "runtime.powerState":
                    pwr_state = prop.Val
                elif prop.Name == "summary.guest.toolsStatus":
                    tools_status = prop.Val

        #Raise an exception if the VM is not powered On.
        if pwr_state not in ["poweredOn"]:
            raise Exception("instance - %s not poweredOn. So can't be "
                            "rebooted." % instance.name)

        #If vmware tools are installed in the VM, then do a guest reboot.
        #Otherwise do a hard reset.
        if tools_status not in ['toolsNotInstalled', 'toolsNotRunning']:
            LOG.debug("Rebooting guest OS of VM %s" % instance.name)
            self._session._call_method(self._session._get_vim(), "RebootGuest",
                                       vm_ref)
            LOG.debug("Rebooted guest OS of VM %s" % instance.name)
        else:
            LOG.debug("Doing hard reboot of VM %s" % instance.name)
            reset_task = self._session._call_method(self._session._get_vim(),
                                                    "ResetVM_Task", vm_ref)
            self._session._wait_for_task(instance.id, reset_task)
            LOG.debug("Did hard reboot of VM %s" % instance.name)

    def destroy(self, instance):
        """
        Destroy a VM instance. Steps followed are:
        1. Power off the VM, if it is in poweredOn state.
        2. Un-register a VM.
        3. Delete the contents of the folder holding the VM related data
        """
        try:
            vm_ref = self._get_vm_ref_from_the_name(instance.name)
            if vm_ref is None:
                LOG.debug("instance - %s not present" % instance.name)
                return
            lst_properties = ["config.files.vmPathName", "runtime.powerState"]
            props = self._session._call_method(vim_util,
                        "get_object_properties",
                        None, vm_ref, "VirtualMachine", lst_properties)
            pwr_state = None
            for elem in props:
                vm_config_pathname = None
                for prop in elem.PropSet:
                    if prop.Name == "runtime.powerState":
                        pwr_state = prop.Val
                    elif prop.Name == "config.files.vmPathName":
                        vm_config_pathname = prop.Val
            if vm_config_pathname:
                datastore_name, vmx_file_path = \
                            vm_util.split_datastore_path(vm_config_pathname)
            #Power off the VM if it is in PoweredOn state.
            if pwr_state == "poweredOn":
                LOG.debug("Powering off the VM %s" % instance.name)
                poweroff_task = self._session._call_method(
                       self._session._get_vim(),
                       "PowerOffVM_Task", vm_ref)
                self._session._wait_for_task(instance.id, poweroff_task)
                LOG.debug("Powered off the VM %s" % instance.name)

            #Un-register the VM
            try:
                LOG.debug("Unregistering the VM %s" % instance.name)
                self._session._call_method(self._session._get_vim(),
                        "UnregisterVM", vm_ref)
                LOG.debug("Unregistered the VM %s" % instance.name)
            except Exception, excep:
                LOG.warn("In vmwareapi:vmops:destroy, got this exception while"
                         " un-registering the VM: " + str(excep))

            #Delete the folder holding the VM related content on the datastore.
            try:
                dir_ds_compliant_path = vm_util.build_datastore_path(
                                 datastore_name,
                                 os.path.dirname(vmx_file_path))
                LOG.debug("Deleting contents of the VM %s from datastore %s " %
                          (instance.name, datastore_name))
                delete_task = self._session._call_method(
                    self._session._get_vim(),
                    "DeleteDatastoreFile_Task",
                    self._session._get_vim().get_service_content().FileManager,
                    name=dir_ds_compliant_path)
                self._session._wait_for_task(instance.id, delete_task)
                LOG.debug("Deleted contents of the VM %s from datastore %s " %
                          (instance.name, datastore_name))
            except Exception, excep:
                LOG.warn("In vmwareapi:vmops:destroy, "
                             "got this exception while deleting"
                             " the VM contents from the disk: " + str(excep))
        except Exception, e:
            LOG.exception(e)

    def pause(self, instance, callback):
        """
        Pause a VM instance
        """
        return "Not Implemented"

    def unpause(self, instance, callback):
        """
        Un-Pause a VM instance
        """
        return "Not Implemented"

    def suspend(self, instance, callback):
        """
        Suspend the specified instance
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance.name)

        pwr_state = self._session._call_method(vim_util,
                    "get_dynamic_property", vm_ref,
                    "VirtualMachine", "runtime.powerState")
        #Only PoweredOn VMs can be suspended.
        if pwr_state == "poweredOn":
            LOG.debug("Suspending the VM %s " % instance.name)
            suspend_task = self._session._call_method(self._session._get_vim(),
                    "SuspendVM_Task", vm_ref)
            self._wait_with_callback(instance.id, suspend_task, callback)
            LOG.debug("Suspended the VM %s " % instance.name)
        #Raise Exception if VM is poweredOff
        elif pwr_state == "poweredOff":
            raise Exception("instance - %s is poweredOff and hence can't "
                            "be suspended." % instance.name)
        LOG.debug("VM %s was already in suspended state. So returning without "
                  "doing anything" % instance.name)

    def resume(self, instance, callback):
        """
        Resume the specified instance
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance.name)

        pwr_state = self._session._call_method(vim_util,
                                     "get_dynamic_property", vm_ref,
                                     "VirtualMachine", "runtime.powerState")
        if pwr_state.lower() == "suspended":
            LOG.debug("Resuming the VM %s " % instance.name)
            suspend_task = self._session._call_method(
                                        self._session._get_vim(),
                                       "PowerOnVM_Task", vm_ref)
            self._wait_with_callback(instance.id, suspend_task, callback)
            LOG.debug("Resumed the VM %s " % instance.name)
        else:
            raise Exception("instance - %s not in Suspended state and hence "
                            "can't be Resumed." % instance.name)

    def get_info(self, instance_name):
        """
        Return data about the VM instance
        """
        vm_ref = self._get_vm_ref_from_the_name(instance_name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance_name)

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
            for prop in elem.PropSet:
                if prop.Name == "summary.config.numCpu":
                    num_cpu = int(prop.Val)
                elif prop.Name == "summary.config..memorySizeMB":
                    # In MB, but we want in KB
                    max_mem = int(prop.Val) * 1024
                elif prop.Name == "runtime.powerState":
                    pwr_state = VMWARE_POWER_STATES[prop.Val]

        return {'state': pwr_state,
                'max_mem': max_mem,
                'mem': max_mem,
                'num_cpu': num_cpu,
                'cpu_time': 0}

    def get_diagnostics(self, instance):
        """
        Return data about VM diagnostics
        """
        return "Not Implemented"

    def get_console_output(self, instance):
        """
        Return snapshot of console
        """
        return 'FAKE CONSOLE OUTPUT of instance'

    def get_ajax_console(self, instance):
        """
        Return link to instance's ajax console
        """
        return 'http://fakeajaxconsole/fake_url'

    def _set_machine_id(self, instance):
        """
        Set the machine id of the VM for guest tools to pick up and change the
        IP
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref is None:
            raise Exception("instance - %s not present" % instance.name)
        network = db.network_get_by_instance(context.get_admin_context(),
                                            instance['id'])
        mac_addr = instance.mac_address
        net_mask = network["netmask"]
        gateway = network["gateway"]
        ip_addr = db.instance_get_fixed_address(context.get_admin_context(),
                                            instance['id'])
        machine_id_chanfge_spec = vm_util.get_machine_id_change_spec(mac_addr,
                                        ip_addr, net_mask, gateway)
        LOG.debug("Reconfiguring VM instance %s to set the machine id "
                  "with ip - %s" % (instance.name, ip_addr))
        reconfig_task = self._session._call_method(self._session._get_vim(),
                           "ReconfigVM_Task", vm_ref,
                           spec=machine_id_chanfge_spec)
        self._session._wait_for_task(instance.id, reconfig_task)
        LOG.debug("Reconfigured VM instance %s to set the machine id "
                  "with ip - %s" % (instance.name, ip_addr))

    def _create_dummy_vm_for_test(self, instance):
        """
        Create a dummy VM for testing purpose
        """
        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        if vm_ref:
            raise Exception('Attempted to create a VM with a name %s, '
                'but that already exists on the host' % instance.name)

        data_stores = self._session._call_method(vim_util, "get_objects",
                    "Datastore", ["summary.type", "summary.name"])
        data_store_name = None
        for elem in data_stores:
            ds_name = None
            ds_type = None
            for prop in elem.PropSet:
                if prop.Name == "summary.type":
                    ds_type = prop.Val
                elif prop.Name == "summary.name":
                    ds_name = prop.Val
            #Local storage identifier
            if ds_type == "VMFS":
                data_store_name = ds_name
                break

        if data_store_name is None:
            msg = "Couldn't get a local Datastore reference"
            LOG.exception(msg)
            raise Exception(msg)

        config_spec = vm_util.get_dummy_vm_create_spec(instance.name,
                                                       data_store_name)

        #Get the Vm folder ref from the datacenter
        dc_objs = self._session._call_method(vim_util, "get_objects",
                                "Datacenter", ["vmFolder"])
        #There is only one default datacenter in a standalone ESX host
        vm_folder_ref = dc_objs[0].PropSet[0].Val

        #Get the resource pool. Taking the first resource pool coming our way.
        #Assuming that is the default resource pool.
        res_pool_mor = self._session._call_method(vim_util, "get_objects",
                                "ResourcePool")[0].Obj

        #Create the VM on the ESX host
        vm_create_task = self._session._call_method(self._session._get_vim(),
                                "CreateVM_Task", vm_folder_ref,
                                config=config_spec, pool=res_pool_mor)
        self._session._wait_for_task(instance.id, vm_create_task)

        vm_ref = self._get_vm_ref_from_the_name(instance.name)
        power_on_task = self._session._call_method(self._session._get_vim(),
                           "PowerOnVM_Task", vm_ref)
        self._session._wait_for_task(instance.id, power_on_task)

    def _get_network_with_the_name(self, network_name="vmnet0"):
        '''
        Gets reference to the network whose name is passed as the argument.
        '''
        datacenters = self._session._call_method(vim_util, "get_objects",
                    "Datacenter", ["network"])
        vm_networks = datacenters[0].PropSet[0].Val.ManagedObjectReference
        networks = self._session._call_method(vim_util,
                           "get_properites_for_a_collection_of_objects",
                           "Network", vm_networks, ["summary.name"])
        for network in networks:
            if network.PropSet[0].Val == network_name:
                return network.Obj
        return None

    def _get_datacenter_name_and_ref(self):
        """
        Get the datacenter name and the reference.
        """
        dc_obj = self._session._call_method(vim_util, "get_objects",
                "Datacenter", ["name"])
        return dc_obj[0].Obj, dc_obj[0].PropSet[0].Val

    def _path_exists(self, ds_browser, ds_path):
        """
        Check if the path exists on the datastore
        """
        search_task = self._session._call_method(self._session._get_vim(),
                                   "SearchDatastore_Task",
                                   ds_browser,
                                   datastorePath=ds_path)
        #Wait till the state changes from queued or running.
        #If an error state is returned, it means that the path doesn't exist.
        while True:
            task_info = self._session._call_method(vim_util,
                                       "get_dynamic_property",
                                       search_task, "Task", "info")
            if task_info.State in  ['queued', 'running']:
                time.sleep(2)
                continue
            break
        if task_info.State == "error":
            return False
        return True

    def _mkdir(self, ds_path):
        """
        Creates a directory at the path specified. If it is just "NAME", then a
        directory with this name is formed at the topmost level of the
        DataStore.
        """
        LOG.debug("Creating directory with path %s" % ds_path)
        self._session._call_method(self._session._get_vim(), "MakeDirectory",
                    self._session._get_vim().get_service_content().FileManager,
                    name=ds_path, createParentDirectories=False)
        LOG.debug("Created directory with path %s" % ds_path)

    def _get_vm_ref_from_the_name(self, vm_name):
        """
        Get reference to the VM with the name specified.
        """
        vms = self._session._call_method(vim_util, "get_objects",
                    "VirtualMachine", ["name"])
        for vm in vms:
            if vm.PropSet[0].Val == vm_name:
                return vm.Obj
        return None
