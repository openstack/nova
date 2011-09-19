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
The VMware API VM utility module to build SOAP object specs.
"""


def build_datastore_path(datastore_name, path):
    """Build the datastore compliant path."""
    return "[%s] %s" % (datastore_name, path)


def split_datastore_path(datastore_path):
    """
    Split the VMWare style datastore path to get the Datastore
    name and the entity path.
    """
    spl = datastore_path.split('[', 1)[1].split(']', 1)
    path = ""
    if len(spl) == 1:
        datastore_url = spl[0]
    else:
        datastore_url, path = spl
    return datastore_url, path.strip()


def get_vm_create_spec(client_factory, instance, data_store_name,
                       vif_infos, os_type="otherGuest"):
    """Builds the VM Create spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    config_spec.name = instance.name
    config_spec.guestId = os_type

    vm_file_info = client_factory.create('ns0:VirtualMachineFileInfo')
    vm_file_info.vmPathName = "[" + data_store_name + "]"
    config_spec.files = vm_file_info

    tools_info = client_factory.create('ns0:ToolsConfigInfo')
    tools_info.afterPowerOn = True
    tools_info.afterResume = True
    tools_info.beforeGuestStandby = True
    tools_info.beforeGuestShutdown = True
    tools_info.beforeGuestReboot = True

    config_spec.tools = tools_info
    config_spec.numCPUs = int(instance.vcpus)
    config_spec.memoryMB = int(instance.memory_mb)

    vif_spec_list = []
    for vif_info in vif_infos:
        vif_spec = create_network_spec(client_factory, vif_info)
        vif_spec_list.append(vif_spec)

    device_config_spec = vif_spec_list

    config_spec.deviceChange = device_config_spec
    return config_spec


def create_controller_spec(client_factory, key):
    """
    Builds a Config Spec for the LSI Logic Controller's addition
    which acts as the controller for the virtual hard disk to be attached
    to the VM.
    """
    # Create a controller for the Virtual Hard Disk
    virtual_device_config = \
        client_factory.create('ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    virtual_lsi = \
        client_factory.create('ns0:VirtualLsiLogicController')
    virtual_lsi.key = key
    virtual_lsi.busNumber = 0
    virtual_lsi.sharedBus = "noSharing"
    virtual_device_config.device = virtual_lsi
    return virtual_device_config


def create_network_spec(client_factory, vif_info):
    """
    Builds a config spec for the addition of a new network
    adapter to the VM.
    """
    network_spec = \
         client_factory.create('ns0:VirtualDeviceConfigSpec')
    network_spec.operation = "add"

    # Get the recommended card type for the VM based on the guest OS of the VM
    net_device = client_factory.create('ns0:VirtualPCNet32')

    # NOTE(asomya): Only works on ESXi if the portgroup binding is set to
    # ephemeral. Invalid configuration if set to static and the NIC does
    # not come up on boot if set to dynamic.
    network_ref = vif_info['network_ref']
    network_name = vif_info['network_name']
    mac_address = vif_info['mac_address']
    backing = None
    if (network_ref and
        network_ref['type'] == "DistributedVirtualPortgroup"):
        backing_name = \
         'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo'
        backing = \
         client_factory.create(backing_name)
        portgroup = \
         client_factory.create('ns0:DistributedVirtualSwitchPortConnection')
        portgroup.switchUuid = network_ref['dvsw']
        portgroup.portgroupKey = network_ref['dvpg']
        backing.port = portgroup
    else:
        backing = \
         client_factory.create('ns0:VirtualEthernetCardNetworkBackingInfo')
        backing.deviceName = network_name

    connectable_spec = \
        client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = True
    connectable_spec.connected = True

    net_device.connectable = connectable_spec
    net_device.backing = backing

    # The Server assigns a Key to the device. Here we pass a -ve temporary key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    net_device.key = -47
    net_device.addressType = "manual"
    net_device.macAddress = mac_address
    net_device.wakeOnLanEnabled = True

    network_spec.device = net_device
    return network_spec


def get_vmdk_attach_config_spec(client_factory, disksize, file_path,
                                adapter_type="lsiLogic"):
    """Builds the vmdk attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    # The controller Key pertains to the Key of the LSI Logic Controller, which
    # controls this Hard Disk
    device_config_spec = []
    # For IDE devices, there are these two default controllers created in the
    # VM having keys 200 and 201
    if adapter_type == "ide":
        controller_key = 200
    else:
        controller_key = -101
        controller_spec = create_controller_spec(client_factory,
                                            controller_key)
        device_config_spec.append(controller_spec)
    virtual_device_config_spec = create_virtual_disk_spec(client_factory,
                                disksize, controller_key, file_path)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vmdk_file_path_and_adapter_type(client_factory, hardware_devices):
    """Gets the vmdk file path and the storage adapter type."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice
    vmdk_file_path = None
    vmdk_controler_key = None

    adapter_type_dict = {}
    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk" and \
            device.backing.__class__.__name__ \
                == "VirtualDiskFlatVer2BackingInfo":
            vmdk_file_path = device.backing.fileName
            vmdk_controler_key = device.controllerKey
        elif device.__class__.__name__ == "VirtualLsiLogicController":
            adapter_type_dict[device.key] = "lsiLogic"
        elif device.__class__.__name__ == "VirtualBusLogicController":
            adapter_type_dict[device.key] = "busLogic"
        elif device.__class__.__name__ == "VirtualIDEController":
            adapter_type_dict[device.key] = "ide"
        elif device.__class__.__name__ == "VirtualLsiLogicSASController":
            adapter_type_dict[device.key] = "lsiLogic"

    adapter_type = adapter_type_dict.get(vmdk_controler_key, "")

    return vmdk_file_path, adapter_type


def get_copy_virtual_disk_spec(client_factory, adapter_type="lsilogic"):
    """Builds the Virtual Disk copy spec."""
    dest_spec = client_factory.create('ns0:VirtualDiskSpec')
    dest_spec.adapterType = adapter_type
    dest_spec.diskType = "thick"
    return dest_spec


def get_vmdk_create_spec(client_factory, size_in_kb, adapter_type="lsiLogic"):
    """Builds the virtual disk create spec."""
    create_vmdk_spec = \
        client_factory.create('ns0:FileBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = adapter_type
    create_vmdk_spec.diskType = "thick"
    create_vmdk_spec.capacityKb = size_in_kb
    return create_vmdk_spec


def create_virtual_disk_spec(client_factory, disksize, controller_key,
                             file_path=None):
    """
    Builds spec for the creation of a new/ attaching of an already existing
    Virtual Disk to the VM.
    """
    virtual_device_config = \
        client_factory.create('ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if file_path is None:
        virtual_device_config.fileOperation = "create"

    virtual_disk = client_factory.create('ns0:VirtualDisk')

    disk_file_backing = \
        client_factory.create('ns0:VirtualDiskFlatVer2BackingInfo')
    disk_file_backing.diskMode = "persistent"
    disk_file_backing.thinProvisioned = False
    if file_path is not None:
        disk_file_backing.fileName = file_path
    else:
        disk_file_backing.fileName = ""

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = True

    virtual_disk.backing = disk_file_backing
    virtual_disk.connectable = connectable_spec

    # The Server assigns a Key to the device. Here we pass a -ve random key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    virtual_disk.key = -100
    virtual_disk.controllerKey = controller_key
    virtual_disk.unitNumber = 0
    virtual_disk.capacityInKB = disksize

    virtual_device_config.device = virtual_disk

    return virtual_device_config


def get_dummy_vm_create_spec(client_factory, name, data_store_name):
    """Builds the dummy VM create spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    config_spec.name = name
    config_spec.guestId = "otherGuest"

    vm_file_info = client_factory.create('ns0:VirtualMachineFileInfo')
    vm_file_info.vmPathName = "[" + data_store_name + "]"
    config_spec.files = vm_file_info

    tools_info = client_factory.create('ns0:ToolsConfigInfo')
    tools_info.afterPowerOn = True
    tools_info.afterResume = True
    tools_info.beforeGuestStandby = True
    tools_info.beforeGuestShutdown = True
    tools_info.beforeGuestReboot = True

    config_spec.tools = tools_info
    config_spec.numCPUs = 1
    config_spec.memoryMB = 4

    controller_key = -101
    controller_spec = create_controller_spec(client_factory, controller_key)
    disk_spec = create_virtual_disk_spec(client_factory, 1024, controller_key)

    device_config_spec = [controller_spec, disk_spec]

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_machine_id_change_spec(client_factory, machine_id_str):
    """Builds the machine id change config spec."""
    virtual_machine_config_spec = \
        client_factory.create('ns0:VirtualMachineConfigSpec')

    opt = client_factory.create('ns0:OptionValue')
    opt.key = "machine.id"
    opt.value = machine_id_str
    virtual_machine_config_spec.extraConfig = [opt]
    return virtual_machine_config_spec


def get_add_vswitch_port_group_spec(client_factory, vswitch_name,
                                    port_group_name, vlan_id):
    """Builds the virtual switch port group add spec."""
    vswitch_port_group_spec = client_factory.create('ns0:HostPortGroupSpec')
    vswitch_port_group_spec.name = port_group_name
    vswitch_port_group_spec.vswitchName = vswitch_name

    # VLAN ID of 0 means that VLAN tagging is not to be done for the network.
    vswitch_port_group_spec.vlanId = int(vlan_id)

    policy = client_factory.create('ns0:HostNetworkPolicy')
    nicteaming = client_factory.create('ns0:HostNicTeamingPolicy')
    nicteaming.notifySwitches = True
    policy.nicTeaming = nicteaming

    vswitch_port_group_spec.policy = policy
    return vswitch_port_group_spec
