# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

import copy

from nova import exception
from nova.virt.vmwareapi import vim_util


def build_datastore_path(datastore_name, path):
    """Build the datastore compliant path."""
    return "[%s] %s" % (datastore_name, path)


def split_datastore_path(datastore_path):
    """
    Split the VMware style datastore path to get the Datastore
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
    config_spec.name = instance['uuid']
    config_spec.guestId = os_type

    # Allow nested ESX instances to host 64 bit VMs.
    if os_type == "vmkernel5Guest":
        config_spec.nestedHVEnabled = "True"

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
    config_spec.numCPUs = int(instance['vcpus'])
    config_spec.memoryMB = int(instance['memory_mb'])

    vif_spec_list = []
    for vif_info in vif_infos:
        vif_spec = create_network_spec(client_factory, vif_info)
        vif_spec_list.append(vif_spec)

    device_config_spec = vif_spec_list

    config_spec.deviceChange = device_config_spec

    # add vm-uuid and iface-id.x values for Quantum
    extra_config = []
    opt = client_factory.create('ns0:OptionValue')
    opt.key = "nvp.vm-uuid"
    opt.value = instance['uuid']
    extra_config.append(opt)

    i = 0
    for vif_info in vif_infos:
        if vif_info['iface_id']:
            opt = client_factory.create('ns0:OptionValue')
            opt.key = "nvp.iface-id.%d" % i
            opt.value = vif_info['iface_id']
            extra_config.append(opt)
            i += 1

    config_spec.extraConfig = extra_config

    return config_spec


def create_controller_spec(client_factory, key, adapter_type="lsiLogic"):
    """
    Builds a Config Spec for the LSI or Bus Logic Controller's addition
    which acts as the controller for the virtual hard disk to be attached
    to the VM.
    """
    # Create a controller for the Virtual Hard Disk
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if adapter_type == "busLogic":
        virtual_controller = client_factory.create(
                                'ns0:VirtualBusLogicController')
    else:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicController')
    virtual_controller.key = key
    virtual_controller.busNumber = 0
    virtual_controller.sharedBus = "noSharing"
    virtual_device_config.device = virtual_controller
    return virtual_device_config


def create_network_spec(client_factory, vif_info):
    """
    Builds a config spec for the addition of a new network
    adapter to the VM.
    """
    network_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    network_spec.operation = "add"

    # Keep compatible with other Hyper vif model parameter.
    if vif_info['vif_model'] == "e1000":
        vif_info['vif_model'] = "VirtualE1000"

    vif = 'ns0:' + vif_info['vif_model']
    net_device = client_factory.create(vif)

    # NOTE(asomya): Only works on ESXi if the portgroup binding is set to
    # ephemeral. Invalid configuration if set to static and the NIC does
    # not come up on boot if set to dynamic.
    network_ref = vif_info['network_ref']
    network_name = vif_info['network_name']
    mac_address = vif_info['mac_address']
    backing = None
    if (network_ref and
        network_ref['type'] == "DistributedVirtualPortgroup"):
        backing_name = ''.join(['ns0:VirtualEthernetCardDistributed',
                                'VirtualPortBackingInfo'])
        backing = client_factory.create(backing_name)
        portgroup = client_factory.create(
                    'ns0:DistributedVirtualSwitchPortConnection')
        portgroup.switchUuid = network_ref['dvsw']
        portgroup.portgroupKey = network_ref['dvpg']
        backing.port = portgroup
    else:
        backing = client_factory.create(
                  'ns0:VirtualEthernetCardNetworkBackingInfo')
        backing.deviceName = network_name

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
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


def get_vmdk_attach_config_spec(client_factory,
                                adapter_type="lsiLogic",
                                disk_type="preallocated",
                                file_path=None,
                                disk_size=None,
                                linked_clone=False,
                                controller_key=None,
                                unit_number=None,
                                device_name=None):
    """Builds the vmdk attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    # The controller Key pertains to the Key of the LSI Logic Controller, which
    # controls this Hard Disk
    device_config_spec = []
    # For IDE devices, there are these two default controllers created in the
    # VM having keys 200 and 201
    if controller_key is None:
        if adapter_type == "ide":
            controller_key = 200
        else:
            controller_key = -101
            controller_spec = create_controller_spec(client_factory,
                                                     controller_key,
                                                     adapter_type)
            device_config_spec.append(controller_spec)
    virtual_device_config_spec = create_virtual_disk_spec(client_factory,
                                controller_key, disk_type, file_path,
                                disk_size, linked_clone,
                                unit_number, device_name)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vmdk_detach_config_spec(client_factory, device):
    """Builds the vmdk detach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = delete_virtual_disk_spec(client_factory,
                                                          device)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vmdk_path_and_adapter_type(hardware_devices):
    """Gets the vmdk file path and the storage adapter type."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice
    vmdk_file_path = None
    vmdk_controler_key = None
    disk_type = None
    unit_number = 0

    adapter_type_dict = {}
    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if device.backing.__class__.__name__ == \
                    "VirtualDiskFlatVer2BackingInfo":
                vmdk_file_path = device.backing.fileName
                vmdk_controler_key = device.controllerKey
                if getattr(device.backing, 'thinProvisioned', False):
                    disk_type = "thin"
                else:
                    if getattr(device.backing, 'eagerlyScrub', False):
                        disk_type = "eagerZeroedThick"
                    else:
                        disk_type = "preallocated"
            if device.unitNumber > unit_number:
                unit_number = device.unitNumber
        elif device.__class__.__name__ == "VirtualLsiLogicController":
            adapter_type_dict[device.key] = "lsiLogic"
        elif device.__class__.__name__ == "VirtualBusLogicController":
            adapter_type_dict[device.key] = "busLogic"
        elif device.__class__.__name__ == "VirtualIDEController":
            adapter_type_dict[device.key] = "ide"
        elif device.__class__.__name__ == "VirtualLsiLogicSASController":
            adapter_type_dict[device.key] = "lsiLogic"

    adapter_type = adapter_type_dict.get(vmdk_controler_key, "")

    return (vmdk_file_path, vmdk_controler_key, adapter_type,
            disk_type, unit_number)


def get_rdm_disk(hardware_devices, uuid):
    """Gets the RDM disk key."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
            device.backing.__class__.__name__ ==
                "VirtualDiskRawDiskMappingVer1BackingInfo" and
            device.backing.lunUuid == uuid):
            return device


def get_copy_virtual_disk_spec(client_factory, adapter_type="lsilogic",
                               disk_type="preallocated"):
    """Builds the Virtual Disk copy spec."""
    dest_spec = client_factory.create('ns0:VirtualDiskSpec')
    dest_spec.adapterType = adapter_type
    dest_spec.diskType = disk_type
    return dest_spec


def get_vmdk_create_spec(client_factory, size_in_kb, adapter_type="lsiLogic",
                         disk_type="preallocated"):
    """Builds the virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:FileBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = adapter_type
    create_vmdk_spec.diskType = disk_type
    create_vmdk_spec.capacityKb = size_in_kb
    return create_vmdk_spec


def get_rdm_create_spec(client_factory, device, adapter_type="lsiLogic",
                        disk_type="rdmp"):
    """Builds the RDM virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:DeviceBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = adapter_type
    create_vmdk_spec.diskType = disk_type
    create_vmdk_spec.device = device
    return create_vmdk_spec


def create_virtual_disk_spec(client_factory, controller_key,
                             disk_type="preallocated",
                             file_path=None,
                             disk_size=None,
                             linked_clone=False,
                             unit_number=None,
                             device_name=None):
    """
    Builds spec for the creation of a new/ attaching of an already existing
    Virtual Disk to the VM.
    """
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if (file_path is None) or linked_clone:
        virtual_device_config.fileOperation = "create"

    virtual_disk = client_factory.create('ns0:VirtualDisk')

    if disk_type == "rdm" or disk_type == "rdmp":
        disk_file_backing = client_factory.create(
                            'ns0:VirtualDiskRawDiskMappingVer1BackingInfo')
        disk_file_backing.compatibilityMode = "virtualMode" \
            if disk_type == "rdm" else "physicalMode"
        disk_file_backing.diskMode = "independent_persistent"
        disk_file_backing.deviceName = device_name or ""
    else:
        disk_file_backing = client_factory.create(
                            'ns0:VirtualDiskFlatVer2BackingInfo')
        disk_file_backing.diskMode = "persistent"
        if disk_type == "thin":
            disk_file_backing.thinProvisioned = True
        else:
            if disk_type == "eagerZeroedThick":
                disk_file_backing.eagerlyScrub = True
    disk_file_backing.fileName = file_path or ""

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = True

    if not linked_clone:
        virtual_disk.backing = disk_file_backing
    else:
        virtual_disk.backing = copy.copy(disk_file_backing)
        virtual_disk.backing.fileName = ""
        virtual_disk.backing.parent = disk_file_backing
    virtual_disk.connectable = connectable_spec

    # The Server assigns a Key to the device. Here we pass a -ve random key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    virtual_disk.key = -100
    virtual_disk.controllerKey = controller_key
    virtual_disk.unitNumber = unit_number or 0
    virtual_disk.capacityInKB = disk_size or 0

    virtual_device_config.device = virtual_disk

    return virtual_device_config


def delete_virtual_disk_spec(client_factory, device):
    """
    Builds spec for the deletion of an already existing Virtual Disk from VM.
    """
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "remove"
    virtual_device_config.fileOperation = "destroy"
    virtual_device_config.device = device

    return virtual_device_config


def clone_vm_spec(client_factory, location,
                  power_on=False, snapshot=None, template=False):
    """Builds the VM clone spec."""
    clone_spec = client_factory.create('ns0:VirtualMachineCloneSpec')
    clone_spec.location = location
    clone_spec.powerOn = power_on
    clone_spec.snapshot = snapshot
    clone_spec.template = template
    return clone_spec


def relocate_vm_spec(client_factory, datastore=None, host=None,
                     disk_move_type="moveAllDiskBackingsAndAllowSharing"):
    """Builds the VM relocation spec."""
    rel_spec = client_factory.create('ns0:VirtualMachineRelocateSpec')
    rel_spec.datastore = datastore
    rel_spec.diskMoveType = disk_move_type
    rel_spec.host = host
    return rel_spec


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
    virtual_machine_config_spec = client_factory.create(
                                  'ns0:VirtualMachineConfigSpec')

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


def get_vnc_config_spec(client_factory, port, password):
    """Builds the vnc config spec."""
    virtual_machine_config_spec = client_factory.create(
                                    'ns0:VirtualMachineConfigSpec')

    opt_enabled = client_factory.create('ns0:OptionValue')
    opt_enabled.key = "RemoteDisplay.vnc.enabled"
    opt_enabled.value = "true"
    opt_port = client_factory.create('ns0:OptionValue')
    opt_port.key = "RemoteDisplay.vnc.port"
    opt_port.value = port
    opt_pass = client_factory.create('ns0:OptionValue')
    opt_pass.key = "RemoteDisplay.vnc.password"
    opt_pass.value = password
    virtual_machine_config_spec.extraConfig = [opt_enabled, opt_port, opt_pass]
    return virtual_machine_config_spec


def search_datastore_spec(client_factory, file_name):
    """Builds the datastore search spec."""
    search_spec = client_factory.create('ns0:HostDatastoreBrowserSearchSpec')
    search_spec.matchPattern = [file_name]
    return search_spec


def get_vm_ref_from_name(session, vm_name):
    """Get reference to the VM with the name specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    for vm in vms:
        if vm.propSet[0].val == vm_name:
            return vm.obj
    return None


def get_vm_ref_from_uuid(session, instance_uuid):
    """Get reference to the VM with the uuid specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    for vm in vms:
        if vm.propSet[0].val == instance_uuid:
            return vm.obj


def get_vm_ref(session, instance):
    """Get reference to the VM through uuid or vm name."""
    vm_ref = get_vm_ref_from_uuid(session, instance['uuid'])
    if not vm_ref:
        vm_ref = get_vm_ref_from_name(session, instance['name'])
    if vm_ref is None:
        raise exception.InstanceNotFound(instance_id=instance['uuid'])
    return vm_ref


def get_host_ref_from_id(session, host_id, property_list=None):
    """Get a host reference object for a host_id string."""

    if property_list is None:
        property_list = ['name']

    host_refs = session._call_method(
                    vim_util, "get_objects",
                    "HostSystem", property_list)

    for ref in host_refs:
        if ref.obj.value == host_id:
            return ref


def get_host_id_from_vm_ref(session, vm_ref):
    """
    This method allows you to find the managed object
    ID of the host running a VM. Since vMotion can
    change the value, you should not presume that this
    is a value that you can cache for very long and
    should be prepared to allow for it to change.

    :param session: a vSphere API connection
    :param vm_ref: a reference object to the running VM
    :return: the host_id running the virtual machine
    """

    # to prevent typographical errors below
    property_name = 'runtime.host'

    # a property collector in VMware vSphere Management API
    # is a set of local representations of remote values.
    # property_set here, is a local representation of the
    # properties we are querying for.
    property_set = session._call_method(
            vim_util, "get_object_properties",
            None, vm_ref, vm_ref._type, [property_name])

    prop = property_from_property_set(
        property_name, property_set)

    if prop is not None:
        prop = prop.val.value
    else:
        # reaching here represents an impossible state
        raise RuntimeError(
            "Virtual Machine %s exists without a runtime.host!"
            % (vm_ref))

    return prop


def property_from_property_set(property_name, property_set):
    '''
    Use this method to filter property collector results.

    Because network traffic is expensive, multiple
    VMwareAPI calls will sometimes pile-up properties
    to be collected. That means results may contain
    many different values for multiple purposes.

    This helper will filter a list for a single result
    and filter the properties of that result to find
    the single value of whatever type resides in that
    result. This could be a ManagedObjectReference ID
    or a complex value.

    :param property_name: name of property you want
    :param property_set: all results from query
    :return: the value of the property.
    '''

    for prop in property_set:
        p = _property_from_propSet(prop.propSet, property_name)
        if p is not None:
            return p


def _property_from_propSet(propSet, name='name'):
    for p in propSet:
        if p.name == name:
            return p


def get_host_ref_for_vm(session, instance, props):
    """Get the ESXi host running a VM by its name."""

    vm_ref = get_vm_ref(session, instance)
    host_id = get_host_id_from_vm_ref(session, vm_ref)
    return get_host_ref_from_id(session, host_id, props)


def get_host_name_for_vm(session, instance):
    """Get the ESXi host running a VM by its name."""
    host_ref = get_host_ref_for_vm(session, instance, ['name'])
    return get_host_name_from_host_ref(host_ref)


def get_host_name_from_host_ref(host_ref):
    p = _property_from_propSet(host_ref.propSet)
    if p is not None:
        return p.val


def get_cluster_ref_from_name(session, cluster_name):
    """Get reference to the cluster with the name specified."""
    cls = session._call_method(vim_util, "get_objects",
                               "ClusterComputeResource", ["name"])
    for cluster in cls:
        if cluster.propSet[0].val == cluster_name:
            return cluster.obj
    return None


def get_host_ref(session, cluster=None):
    """Get reference to a host within the cluster specified."""
    if cluster is None:
        host_mor = session._call_method(vim_util, "get_objects",
                                        "HostSystem")[0].obj
    else:
        host_ret = session._call_method(vim_util, "get_dynamic_property",
                                        cluster, "ClusterComputeResource",
                                        "host")
        if host_ret is None:
            return
        if not host_ret.ManagedObjectReference:
            return
        host_mor = host_ret.ManagedObjectReference[0]

    return host_mor


def get_datastore_ref_and_name(session, cluster=None, host=None):
    """Get the datastore list and choose the first local storage."""
    if cluster is None and host is None:
        data_stores = session._call_method(vim_util, "get_objects",
                    "Datastore", ["summary.type", "summary.name",
                                  "summary.capacity", "summary.freeSpace"])
    else:
        if cluster is not None:
            datastore_ret = session._call_method(
                                        vim_util,
                                        "get_dynamic_property", cluster,
                                        "ClusterComputeResource", "datastore")
        else:
            datastore_ret = session._call_method(
                                        vim_util,
                                        "get_dynamic_property", host,
                                        "HostSystem", "datastore")

        if datastore_ret is None:
            raise exception.DatastoreNotFound()
        data_store_mors = datastore_ret.ManagedObjectReference
        data_stores = session._call_method(vim_util,
                                "get_properties_for_a_collection_of_objects",
                                "Datastore", data_store_mors,
                                ["summary.type", "summary.name",
                                 "summary.capacity", "summary.freeSpace"])
    for elem in data_stores:
        ds_name = None
        ds_type = None
        ds_cap = None
        ds_free = None
        for prop in elem.propSet:
            if prop.name == "summary.type":
                ds_type = prop.val
            elif prop.name == "summary.name":
                ds_name = prop.val
            elif prop.name == "summary.capacity":
                ds_cap = prop.val
            elif prop.name == "summary.freeSpace":
                ds_free = prop.val
        # Local storage identifier
        if ds_type == "VMFS" or ds_type == "NFS":
            return elem.obj, ds_name, ds_cap, ds_free

        raise exception.DatastoreNotFound()
