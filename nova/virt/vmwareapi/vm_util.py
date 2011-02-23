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
Utility functions to handle virtual disks, virtual network adapters, VMs etc.

"""

from nova.virt.vmwareapi.VimService_services_types import ns0


def build_datastore_path(datastore_name, path):
    """Builds the datastore compliant path."""
    return "[%s] %s" % (datastore_name, path)


def split_datastore_path(datastore_path):
    """
    Split the VMWare style datastore path to get the Datastore name and the
    entity path
    """
    spl = datastore_path.split('[', 1)[1].split(']', 1)
    path = ""
    if len(spl) == 1:
        datastore_url = spl[0]
    else:
        datastore_url, path = spl
    return datastore_url, path.strip()


def get_vm_create_spec(instance, data_store_name, network_name="vmnet0",
                       os_type="otherGuest"):
    """Builds the VM Create spec."""
    config_spec = ns0.VirtualMachineConfigSpec_Def(
                       "VirtualMachineConfigSpec").pyclass()

    config_spec._name = instance.name
    config_spec._guestId = os_type

    vm_file_info = ns0.VirtualMachineFileInfo_Def(
                        "VirtualMachineFileInfo").pyclass()
    vm_file_info._vmPathName = "[" + data_store_name + "]"
    config_spec._files = vm_file_info

    tools_info = ns0.ToolsConfigInfo_Def("ToolsConfigInfo")
    tools_info._afterPowerOn = True
    tools_info._afterResume = True
    tools_info._beforeGuestStandby = True
    tools_info._bbeforeGuestShutdown = True
    tools_info._beforeGuestReboot = True

    config_spec._tools = tools_info
    config_spec._numCPUs = int(instance.vcpus)
    config_spec._memoryMB = int(instance.memory_mb)

    nic_spec = create_network_spec(network_name, instance.mac_address)

    device_config_spec = [nic_spec]

    config_spec._deviceChange = device_config_spec
    return config_spec


def create_controller_spec(key):
    """
    Builds a Config Spec for the LSI Logic Controller's addition which acts
    as the controller for the Virtual Hard disk to be attached to the VM
    """
    #Create a controller for the Virtual Hard Disk
    virtual_device_config = \
        ns0.VirtualDeviceConfigSpec_Def("VirtualDeviceConfigSpec").pyclass()
    virtual_device_config._operation = "add"
    virtual_lsi = \
        ns0.VirtualLsiLogicController_Def(
                  "VirtualLsiLogicController").pyclass()
    virtual_lsi._key = key
    virtual_lsi._busNumber = 0
    virtual_lsi._sharedBus = "noSharing"
    virtual_device_config._device = virtual_lsi

    return virtual_device_config


def create_network_spec(network_name, mac_address):
    """
    Builds a config spec for the addition of a new network adapter to
    the VM.
    """
    network_spec = \
        ns0.VirtualDeviceConfigSpec_Def("VirtualDeviceConfigSpec").pyclass()
    network_spec._operation = "add"

    #Get the recommended card type for the VM based on the guest OS of the VM
    net_device = ns0.VirtualPCNet32_Def("VirtualPCNet32").pyclass()

    backing = \
        ns0.VirtualEthernetCardNetworkBackingInfo_Def(
        "VirtualEthernetCardNetworkBackingInfo").pyclass()
    backing._deviceName = network_name

    connectable_spec = \
        ns0.VirtualDeviceConnectInfo_Def("VirtualDeviceConnectInfo").pyclass()
    connectable_spec._startConnected = True
    connectable_spec._allowGuestControl = True
    connectable_spec._connected = True

    net_device._connectable = connectable_spec
    net_device._backing = backing

    #The Server assigns a Key to the device. Here we pass a -ve temporary key.
    #-ve because actual keys are +ve numbers and we don't
    #want a clash with the key that server might associate with the device
    net_device._key = -47
    net_device._addressType = "manual"
    net_device._macAddress = mac_address
    net_device._wakeOnLanEnabled = True

    network_spec._device = net_device
    return network_spec


def get_datastore_search_sepc(pattern=None):
    """Builds the datastore search spec."""
    host_datastore_browser_search_spec = \
        ns0.HostDatastoreBrowserSearchSpec_Def(
                       "HostDatastoreBrowserSearchSpec").pyclass()
    file_query_flags = ns0.FileQueryFlags_Def("FileQueryFlags").pyclass()
    file_query_flags._modification = False
    file_query_flags._fileSize = True
    file_query_flags._fileType = True
    file_query_flags._fileOwner = True
    host_datastore_browser_search_spec._details = file_query_flags
    if pattern is not None:
        host_datastore_browser_search_spec._matchPattern = pattern
    return host_datastore_browser_search_spec


def get_vmdk_attach_config_sepc(disksize, file_path, adapter_type="lsiLogic"):
    """Builds the vmdk attach config spec."""
    config_spec = ns0.VirtualMachineConfigSpec_Def(
                       "VirtualMachineConfigSpec").pyclass()

    #The controller Key pertains to the Key of the LSI Logic Controller, which
    #controls this Hard Disk
    device_config_spec = []
    #For IDE devices, there are these two default controllers created in the
    #VM having keys 200 and 201
    if adapter_type == "ide":
        controller_key = 200
    else:
        controller_key = -101
        controller_spec = create_controller_spec(controller_key)
        device_config_spec.append(controller_spec)
    virtual_device_config_spec = create_virtual_disk_spec(disksize,
                                controller_key, file_path)

    device_config_spec.append(virtual_device_config_spec)

    config_spec._deviceChange = device_config_spec
    return config_spec


def get_vmdk_file_path_and_adapter_type(hardware_devices):
    """Gets the vmdk file path and the storage adapter type."""
    if isinstance(hardware_devices.typecode, ns0.ArrayOfVirtualDevice_Def):
        hardware_devices = hardware_devices.VirtualDevice
    vmdk_file_path = None
    vmdk_controler_key = None

    adapter_type_dict = {}
    for device in hardware_devices:
        if (isinstance(device.typecode, ns0.VirtualDisk_Def) and
            isinstance(device.Backing.typecode,
                       ns0.VirtualDiskFlatVer2BackingInfo_Def)):
            vmdk_file_path = device.Backing.FileName
            vmdk_controler_key = device.ControllerKey
        elif isinstance(device.typecode, ns0.VirtualLsiLogicController_Def):
            adapter_type_dict[device.Key] = "lsiLogic"
        elif isinstance(device.typecode, ns0.VirtualBusLogicController_Def):
            adapter_type_dict[device.Key] = "busLogic"
        elif isinstance(device.typecode, ns0.VirtualIDEController_Def):
            adapter_type_dict[device.Key] = "ide"
        elif isinstance(device.typecode, ns0.VirtualLsiLogicSASController_Def):
            adapter_type_dict[device.Key] = "lsiLogic"

    adapter_type = adapter_type_dict.get(vmdk_controler_key, "")

    return vmdk_file_path, adapter_type


def get_copy_virtual_disk_spec(adapter_type="lsilogic"):
    """Builds the Virtual Disk copy spec."""
    dest_spec = ns0.VirtualDiskSpec_Def("VirtualDiskSpec").pyclass()
    dest_spec.AdapterType = adapter_type
    dest_spec.DiskType = "thick"
    return dest_spec


def get_vmdk_create_spec(size_in_kb, adapter_type="lsiLogic"):
    """Builds the virtual disk create sepc."""
    create_vmdk_spec = \
        ns0.FileBackedVirtualDiskSpec_Def("VirtualDiskSpec").pyclass()
    create_vmdk_spec._adapterType = adapter_type
    create_vmdk_spec._diskType = "thick"
    create_vmdk_spec._capacityKb = size_in_kb
    return create_vmdk_spec


def create_virtual_disk_spec(disksize, controller_key, file_path=None):
    """Creates a Spec for the addition/attaching of a Virtual Disk to the VM"""
    virtual_device_config = \
        ns0.VirtualDeviceConfigSpec_Def("VirtualDeviceConfigSpec").pyclass()
    virtual_device_config._operation = "add"
    if file_path is None:
        virtual_device_config._fileOperation = "create"

    virtual_disk = ns0.VirtualDisk_Def("VirtualDisk").pyclass()

    disk_file_backing = ns0.VirtualDiskFlatVer2BackingInfo_Def(
                             "VirtualDiskFlatVer2BackingInfo").pyclass()
    disk_file_backing._diskMode = "persistent"
    disk_file_backing._thinProvisioned = False
    if file_path is not None:
        disk_file_backing._fileName = file_path
    else:
        disk_file_backing._fileName = ""

    connectable_spec = ns0.VirtualDeviceConnectInfo_Def(
                               "VirtualDeviceConnectInfo").pyclass()
    connectable_spec._startConnected = True
    connectable_spec._allowGuestControl = False
    connectable_spec._connected = True

    virtual_disk._backing = disk_file_backing
    virtual_disk._connectable = connectable_spec

    #The Server assigns a Key to the device. Here we pass a -ve temporary key.
    #-ve because actual keys are +ve numbers and we don't
    #want a clash with the key that server might associate with the device
    virtual_disk._key = -100
    virtual_disk._controllerKey = controller_key
    virtual_disk._unitNumber = 0
    virtual_disk._capacityInKB = disksize

    virtual_device_config._device = virtual_disk

    return virtual_device_config


def get_dummy_vm_create_spec(name, data_store_name):
    """Builds the dummy VM create spec."""
    config_spec = ns0.VirtualMachineConfigSpec_Def(
                               "VirtualMachineConfigSpec").pyclass()

    config_spec._name = name
    config_spec._guestId = "otherGuest"

    vm_file_info = ns0.VirtualMachineFileInfo_Def(
                                "VirtualMachineFileInfo").pyclass()
    vm_file_info._vmPathName = "[" + data_store_name + "]"
    config_spec._files = vm_file_info

    tools_info = ns0.ToolsConfigInfo_Def("ToolsConfigInfo")
    tools_info._afterPowerOn = True
    tools_info._afterResume = True
    tools_info._beforeGuestStandby = True
    tools_info._bbeforeGuestShutdown = True
    tools_info._beforeGuestReboot = True

    config_spec._tools = tools_info
    config_spec._numCPUs = 1
    config_spec._memoryMB = 4

    controller_key = -101
    controller_spec = create_controller_spec(controller_key)
    disk_spec = create_virtual_disk_spec(1024, controller_key)

    device_config_spec = [controller_spec, disk_spec]

    config_spec._deviceChange = device_config_spec
    return config_spec


def get_machine_id_change_spec(mac, ip_addr, netmask, gateway):
    """Builds the machine id change config spec."""
    machine_id_str = "%s;%s;%s;%s" % (mac, ip_addr, netmask, gateway)
    virtual_machine_config_spec = ns0.VirtualMachineConfigSpec_Def(
                                       "VirtualMachineConfigSpec").pyclass()
    opt = ns0.OptionValue_Def('OptionValue').pyclass()
    opt._key = "machine.id"
    opt._value = machine_id_str
    virtual_machine_config_spec._extraConfig = [opt]
    return virtual_machine_config_spec
