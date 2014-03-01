# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

import collections
import copy
import functools

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils
from nova.virt.vmwareapi import vim_util

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

DSRecord = collections.namedtuple(
    'DSRecord', ['datastore', 'name', 'capacity', 'freespace'])

# A cache for VM references. The key will be the VM name
# and the value is the VM reference. The VM name is unique. This
# is either the UUID of the instance or UUID-rescue in the case
# that this is a rescue VM. This is in order to prevent
# unnecessary communication with the backend.
_VM_REFS_CACHE = {}


def vm_refs_cache_reset():
    global _VM_REFS_CACHE
    _VM_REFS_CACHE = {}


def vm_ref_cache_delete(id):
    _VM_REFS_CACHE.pop(id, None)


def vm_ref_cache_update(id, vm_ref):
    _VM_REFS_CACHE[id] = vm_ref


def vm_ref_cache_get(id):
    return _VM_REFS_CACHE.get(id)


def _vm_ref_cache(id, func, session, data):
    vm_ref = vm_ref_cache_get(id)
    if not vm_ref:
        vm_ref = func(session, data)
        vm_ref_cache_update(id, vm_ref)
    return vm_ref


def vm_ref_cache_from_instance(func):
    @functools.wraps(func)
    def wrapper(session, instance):
        id = instance['uuid']
        return _vm_ref_cache(id, func, session, instance)
    return wrapper


def vm_ref_cache_from_name(func):
    @functools.wraps(func)
    def wrapper(session, name):
        id = name
        return _vm_ref_cache(id, func, session, name)
    return wrapper

# the config key which stores the VNC port
VNC_CONFIG_KEY = 'config.extraConfig["RemoteDisplay.vnc.port"]'


def build_datastore_path(datastore_name, path):
    """Build the datastore compliant path."""
    return "[%s] %s" % (datastore_name, path)


def split_datastore_path(datastore_path):
    """Split the VMware style datastore path to get the Datastore
    name and the entity path.
    """
    spl = datastore_path.split('[', 1)[1].split(']', 1)
    path = ""
    if len(spl) == 1:
        datastore_url = spl[0]
    else:
        datastore_url, path = spl
    return datastore_url, path.strip()


def get_vm_create_spec(client_factory, instance, name, data_store_name,
                       vif_infos, os_type="otherGuest"):
    """Builds the VM Create spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    config_spec.name = name
    config_spec.guestId = os_type
    # The name is the unique identifier for the VM. This will either be the
    # instance UUID or the instance UUID with suffix '-rescue' for VM's that
    # are in rescue mode
    config_spec.instanceUuid = name

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

    # add vm-uuid and iface-id.x values for Neutron
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


def get_vm_resize_spec(client_factory, instance):
    """Provides updates for a VM spec."""
    resize_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    resize_spec.numCPUs = int(instance['vcpus'])
    resize_spec.memoryMB = int(instance['memory_mb'])
    return resize_spec


def create_controller_spec(client_factory, key, adapter_type="lsiLogic"):
    """Builds a Config Spec for the LSI or Bus Logic Controller's addition
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
    elif adapter_type == "lsiLogicsas":
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicSASController')
    else:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicController')
    virtual_controller.key = key
    virtual_controller.busNumber = 0
    virtual_controller.sharedBus = "noSharing"
    virtual_device_config.device = virtual_controller
    return virtual_device_config


def create_network_spec(client_factory, vif_info):
    """Builds a config spec for the addition of a new network
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
    if network_ref and network_ref['type'] == 'OpaqueNetwork':
        backing_name = ''.join(['ns0:VirtualEthernetCard',
                                'OpaqueNetworkBackingInfo'])
        backing = client_factory.create(backing_name)
        backing.opaqueNetworkId = network_ref['network-id']
        backing.opaqueNetworkType = network_ref['network-type']
    elif (network_ref and
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
                                disk_type="preallocated",
                                file_path=None,
                                disk_size=None,
                                linked_clone=False,
                                controller_key=None,
                                unit_number=None,
                                device_name=None):
    """Builds the vmdk attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = create_virtual_disk_spec(client_factory,
                                controller_key, disk_type, file_path,
                                disk_size, linked_clone,
                                unit_number, device_name)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_cdrom_attach_config_spec(client_factory,
                                 datastore,
                                 file_path,
                                 controller_key,
                                 cdrom_unit_number):
    """Builds and returns the cdrom attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = create_virtual_cdrom_spec(client_factory,
                                                           datastore,
                                                           controller_key,
                                                           file_path,
                                                           cdrom_unit_number)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vmdk_detach_config_spec(client_factory, device,
                                destroy_disk=False):
    """Builds the vmdk detach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = detach_virtual_disk_spec(client_factory,
                                                          device,
                                                          destroy_disk)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_vm_extra_config_spec(client_factory, extra_opts):
    """Builds extra spec fields from a dictionary."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    # add the key value pairs
    extra_config = []
    for key, value in extra_opts.iteritems():
        opt = client_factory.create('ns0:OptionValue')
        opt.key = key
        opt.value = value
        extra_config.append(opt)
        config_spec.extraConfig = extra_config
    return config_spec


def get_vmdk_path_and_adapter_type(hardware_devices, uuid=None):
    """Gets the vmdk file path and the storage adapter type."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice
    vmdk_file_path = None
    vmdk_controller_key = None
    disk_type = None

    adapter_type_dict = {}
    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if device.backing.__class__.__name__ == \
                    "VirtualDiskFlatVer2BackingInfo":
                if uuid:
                    if uuid in device.backing.fileName:
                        vmdk_file_path = device.backing.fileName
                else:
                    vmdk_file_path = device.backing.fileName
                vmdk_controller_key = device.controllerKey
                if getattr(device.backing, 'thinProvisioned', False):
                    disk_type = "thin"
                else:
                    if getattr(device.backing, 'eagerlyScrub', False):
                        disk_type = "eagerZeroedThick"
                    else:
                        disk_type = "preallocated"
        elif device.__class__.__name__ == "VirtualLsiLogicController":
            adapter_type_dict[device.key] = "lsiLogic"
        elif device.__class__.__name__ == "VirtualBusLogicController":
            adapter_type_dict[device.key] = "busLogic"
        elif device.__class__.__name__ == "VirtualIDEController":
            adapter_type_dict[device.key] = "ide"
        elif device.__class__.__name__ == "VirtualLsiLogicSASController":
            adapter_type_dict[device.key] = "lsiLogicsas"

    adapter_type = adapter_type_dict.get(vmdk_controller_key, "")

    return (vmdk_file_path, adapter_type, disk_type)


def _find_controller_slot(controller_keys, taken, max_unit_number):
    for controller_key in controller_keys:
        for unit_number in range(max_unit_number):
            if not unit_number in taken.get(controller_key, []):
                return controller_key, unit_number


def _is_ide_controller(device):
    return device.__class__.__name__ == 'VirtualIDEController'


def _is_scsi_controller(device):
    return device.__class__.__name__ in ['VirtualLsiLogicController',
                                         'VirtualLsiLogicSASController',
                                         'VirtualBusLogicController']


def _find_allocated_slots(devices):
    """Return dictionary which maps controller_key to list of allocated unit
    numbers for that controller_key.
    """
    taken = {}
    for device in devices:
        if hasattr(device, 'controllerKey') and hasattr(device, 'unitNumber'):
            unit_numbers = taken.setdefault(device.controllerKey, [])
            unit_numbers.append(device.unitNumber)
        if _is_scsi_controller(device):
            # the SCSI controller sits on its own bus
            unit_numbers = taken.setdefault(device.key, [])
            unit_numbers.append(device.scsiCtlrUnitNumber)
    return taken


def allocate_controller_key_and_unit_number(client_factory, devices,
                                            adapter_type):
    """This function inspects the current set of hardware devices and returns
    controller_key and unit_number that can be used for attaching a new virtual
    disk to adapter with the given adapter_type.
    """
    if devices.__class__.__name__ == "ArrayOfVirtualDevice":
        devices = devices.VirtualDevice

    taken = _find_allocated_slots(devices)

    ret = None
    if adapter_type == 'ide':
        ide_keys = [dev.key for dev in devices if _is_ide_controller(dev)]
        ret = _find_controller_slot(ide_keys, taken, 2)
    elif adapter_type in ['lsiLogic', 'lsiLogicsas', 'busLogic']:
        scsi_keys = [dev.key for dev in devices if _is_scsi_controller(dev)]
        ret = _find_controller_slot(scsi_keys, taken, 16)
    if ret:
        return ret[0], ret[1], None

    # create new controller with the specified type and return its spec
    controller_key = -101
    controller_spec = create_controller_spec(client_factory, controller_key,
                                             adapter_type)
    return controller_key, 0, controller_spec


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


def get_copy_virtual_disk_spec(client_factory, adapter_type="lsiLogic",
                               disk_type="preallocated"):
    """Builds the Virtual Disk copy spec."""
    dest_spec = client_factory.create('ns0:VirtualDiskSpec')
    dest_spec.adapterType = get_vmdk_adapter_type(adapter_type)
    dest_spec.diskType = disk_type
    return dest_spec


def get_vmdk_create_spec(client_factory, size_in_kb, adapter_type="lsiLogic",
                         disk_type="preallocated"):
    """Builds the virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:FileBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = get_vmdk_adapter_type(adapter_type)
    create_vmdk_spec.diskType = disk_type
    create_vmdk_spec.capacityKb = size_in_kb
    return create_vmdk_spec


def get_rdm_create_spec(client_factory, device, adapter_type="lsiLogic",
                        disk_type="rdmp"):
    """Builds the RDM virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:DeviceBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = get_vmdk_adapter_type(adapter_type)
    create_vmdk_spec.diskType = disk_type
    create_vmdk_spec.device = device
    return create_vmdk_spec


def create_virtual_cdrom_spec(client_factory,
                              datastore,
                              controller_key,
                              file_path,
                              cdrom_unit_number):
    """Builds spec for the creation of a new Virtual CDROM to the VM."""
    config_spec = client_factory.create(
        'ns0:VirtualDeviceConfigSpec')
    config_spec.operation = "add"

    cdrom = client_factory.create('ns0:VirtualCdrom')

    cdrom_device_backing = client_factory.create(
        'ns0:VirtualCdromIsoBackingInfo')
    cdrom_device_backing.datastore = datastore
    cdrom_device_backing.fileName = file_path

    cdrom.backing = cdrom_device_backing
    cdrom.controllerKey = controller_key
    cdrom.unitNumber = cdrom_unit_number
    cdrom.key = -1

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = True

    cdrom.connectable = connectable_spec

    config_spec.device = cdrom
    return config_spec


def create_virtual_disk_spec(client_factory, controller_key,
                             disk_type="preallocated",
                             file_path=None,
                             disk_size=None,
                             linked_clone=False,
                             unit_number=None,
                             device_name=None):
    """Builds spec for the creation of a new/ attaching of an already existing
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


def detach_virtual_disk_spec(client_factory, device, destroy_disk=False):
    """Builds spec for the detach of an already existing Virtual Disk from VM.
    """
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "remove"
    if destroy_disk:
        virtual_device_config.fileOperation = "destroy"
    virtual_device_config.device = device

    return virtual_device_config


def clone_vm_spec(client_factory, location,
                  power_on=False, snapshot=None, template=False):
    """Builds the VM clone spec."""
    clone_spec = client_factory.create('ns0:VirtualMachineCloneSpec')
    clone_spec.location = location
    clone_spec.powerOn = power_on
    if snapshot:
        clone_spec.snapshot = snapshot
    clone_spec.template = template
    return clone_spec


def relocate_vm_spec(client_factory, datastore=None, host=None,
                     disk_move_type="moveAllDiskBackingsAndAllowSharing"):
    """Builds the VM relocation spec."""
    rel_spec = client_factory.create('ns0:VirtualMachineRelocateSpec')
    rel_spec.datastore = datastore
    rel_spec.diskMoveType = disk_move_type
    if host:
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


def get_vnc_config_spec(client_factory, port):
    """Builds the vnc config spec."""
    virtual_machine_config_spec = client_factory.create(
                                    'ns0:VirtualMachineConfigSpec')

    opt_enabled = client_factory.create('ns0:OptionValue')
    opt_enabled.key = "RemoteDisplay.vnc.enabled"
    opt_enabled.value = "true"
    opt_port = client_factory.create('ns0:OptionValue')
    opt_port.key = "RemoteDisplay.vnc.port"
    opt_port.value = port
    extras = [opt_enabled, opt_port]
    virtual_machine_config_spec.extraConfig = extras
    return virtual_machine_config_spec


@utils.synchronized('vmware.get_vnc_port')
def get_vnc_port(session):
    """Return VNC port for an VM or None if there is no available port."""
    min_port = CONF.vmware.vnc_port
    port_total = CONF.vmware.vnc_port_total
    allocated_ports = _get_allocated_vnc_ports(session)
    max_port = min_port + port_total
    for port in range(min_port, max_port):
        if port not in allocated_ports:
            return port
    raise exception.ConsolePortRangeExhausted(min_port=min_port,
                                              max_port=max_port)


def _get_allocated_vnc_ports(session):
    """Return an integer set of all allocated VNC ports."""
    # TODO(rgerganov): bug #1256944
    # The VNC port should be unique per host, not per vCenter
    vnc_ports = set()
    result = session._call_method(vim_util, "get_objects",
                                  "VirtualMachine", [VNC_CONFIG_KEY])
    while result:
        for obj in result.objects:
            if not hasattr(obj, 'propSet'):
                continue
            dynamic_prop = obj.propSet[0]
            option_value = dynamic_prop.val
            vnc_port = option_value.value
            vnc_ports.add(int(vnc_port))
        token = _get_token(result)
        if token:
            result = session._call_method(vim_util,
                                          "continue_to_get_objects",
                                          token)
        else:
            break
    return vnc_ports


def search_datastore_spec(client_factory, file_name):
    """Builds the datastore search spec."""
    search_spec = client_factory.create('ns0:HostDatastoreBrowserSearchSpec')
    search_spec.matchPattern = [file_name]
    return search_spec


def _get_token(results):
    """Get the token from the property results."""
    return getattr(results, 'token', None)


def _get_reference_for_value(results, value):
    for object in results.objects:
        if object.obj.value == value:
            return object


def _get_object_for_value(results, value):
    for object in results.objects:
        if object.propSet[0].val == value:
            return object.obj


def _get_object_for_optionvalue(results, value):
    for object in results.objects:
        if hasattr(object, "propSet") and object.propSet:
            if object.propSet[0].val.value == value:
                return object.obj


def _get_object_from_results(session, results, value, func):
    while results:
        token = _get_token(results)
        object = func(results, value)
        if object:
            if token:
                session._call_method(vim_util,
                                     "cancel_retrieve",
                                     token)
            return object

        if token:
            results = session._call_method(vim_util,
                                           "continue_to_get_objects",
                                           token)
        else:
            return None


def _cancel_retrieve_if_necessary(session, results):
    token = _get_token(results)
    if token:
        results = session._call_method(vim_util,
                                       "cancel_retrieve",
                                       token)


def _get_vm_ref_from_name(session, vm_name):
    """Get reference to the VM with the name specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    return _get_object_from_results(session, vms, vm_name,
                                    _get_object_for_value)


@vm_ref_cache_from_name
def get_vm_ref_from_name(session, vm_name):
    return (_get_vm_ref_from_vm_uuid(session, vm_name) or
            _get_vm_ref_from_name(session, vm_name))


def _get_vm_ref_from_uuid(session, instance_uuid):
    """Get reference to the VM with the uuid specified.

    This method reads all of the names of the VM's that are running
    on the backend, then it filters locally the matching
    instance_uuid. It is far more optimal to use
    _get_vm_ref_from_vm_uuid.
    """
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ["name"])
    return _get_object_from_results(session, vms, instance_uuid,
                                    _get_object_for_value)


def _get_vm_ref_from_vm_uuid(session, instance_uuid):
    """Get reference to the VM.

    The method will make use of FindAllByUuid to get the VM reference.
    This method finds all VM's on the backend that match the
    instance_uuid, more specifically all VM's on the backend that have
    'config_spec.instanceUuid' set to 'instance_uuid'.
    """
    vm_refs = session._call_method(
        session._get_vim(),
        "FindAllByUuid",
        session._get_vim().get_service_content().searchIndex,
        uuid=instance_uuid,
        vmSearch=True,
        instanceUuid=True)
    if vm_refs:
        return vm_refs[0]


def _get_vm_ref_from_extraconfig(session, instance_uuid):
    """Get reference to the VM with the uuid specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ['config.extraConfig["nvp.vm-uuid"]'])
    return _get_object_from_results(session, vms, instance_uuid,
                                     _get_object_for_optionvalue)


@vm_ref_cache_from_instance
def get_vm_ref(session, instance):
    """Get reference to the VM through uuid or vm name."""
    uuid = instance['uuid']
    vm_ref = (_get_vm_ref_from_vm_uuid(session, uuid) or
                  _get_vm_ref_from_extraconfig(session, uuid) or
                  _get_vm_ref_from_uuid(session, uuid) or
                  _get_vm_ref_from_name(session, instance['name']))
    if vm_ref is None:
        raise exception.InstanceNotFound(instance_id=uuid)
    return vm_ref


def get_host_ref_from_id(session, host_id, property_list=None):
    """Get a host reference object for a host_id string."""

    if property_list is None:
        property_list = ['name']

    host_refs = session._call_method(
                    vim_util, "get_objects",
                    "HostSystem", property_list)
    return _get_object_from_results(session, host_refs, host_id,
                                    _get_reference_for_value)


def get_host_id_from_vm_ref(session, vm_ref):
    """This method allows you to find the managed object
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
    '''Use this method to filter property collector results.

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

    for prop in property_set.objects:
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


def get_vm_state_from_name(session, vm_name):
    vm_ref = get_vm_ref_from_name(session, vm_name)
    vm_state = session._call_method(vim_util, "get_dynamic_property",
                vm_ref, "VirtualMachine", "runtime.powerState")
    return vm_state


def get_stats_from_cluster(session, cluster):
    """Get the aggregate resource stats of a cluster."""
    cpu_info = {'vcpus': 0, 'cores': 0, 'vendor': [], 'model': []}
    mem_info = {'total': 0, 'free': 0}
    # Get the Host and Resource Pool Managed Object Refs
    prop_dict = session._call_method(vim_util, "get_dynamic_properties",
                                     cluster, "ClusterComputeResource",
                                     ["host", "resourcePool"])
    if prop_dict:
        host_ret = prop_dict.get('host')
        if host_ret:
            host_mors = host_ret.ManagedObjectReference
            result = session._call_method(vim_util,
                         "get_properties_for_a_collection_of_objects",
                         "HostSystem", host_mors,
                         ["summary.hardware", "summary.runtime"])
            for obj in result.objects:
                hardware_summary = obj.propSet[0].val
                runtime_summary = obj.propSet[1].val
                if runtime_summary.connectionState == "connected":
                    # Total vcpus is the sum of all pCPUs of individual hosts
                    # The overcommitment ratio is factored in by the scheduler
                    cpu_info['vcpus'] += hardware_summary.numCpuThreads
                    cpu_info['cores'] += hardware_summary.numCpuCores
                    cpu_info['vendor'].append(hardware_summary.vendor)
                    cpu_info['model'].append(hardware_summary.cpuModel)

        res_mor = prop_dict.get('resourcePool')
        if res_mor:
            res_usage = session._call_method(vim_util, "get_dynamic_property",
                            res_mor, "ResourcePool", "summary.runtime.memory")
            if res_usage:
                # maxUsage is the memory limit of the cluster available to VM's
                mem_info['total'] = int(res_usage.maxUsage / units.Mi)
                # overallUsage is the hypervisor's view of memory usage by VM's
                consumed = int(res_usage.overallUsage / units.Mi)
                mem_info['free'] = mem_info['total'] - consumed
    stats = {'cpu': cpu_info, 'mem': mem_info}
    return stats


def get_cluster_ref_from_name(session, cluster_name):
    """Get reference to the cluster with the name specified."""
    cls = session._call_method(vim_util, "get_objects",
                               "ClusterComputeResource", ["name"])
    return _get_object_from_results(session, cls, cluster_name,
                                    _get_object_for_value)


def get_host_ref(session, cluster=None):
    """Get reference to a host within the cluster specified."""
    if cluster is None:
        results = session._call_method(vim_util, "get_objects",
                                       "HostSystem")
        _cancel_retrieve_if_necessary(session, results)
        host_mor = results.objects[0].obj
    else:
        host_ret = session._call_method(vim_util, "get_dynamic_property",
                                        cluster, "ClusterComputeResource",
                                        "host")
        if not host_ret or not host_ret.ManagedObjectReference:
            msg = _('No host available on cluster')
            raise exception.NoValidHost(reason=msg)
        host_mor = host_ret.ManagedObjectReference[0]

    return host_mor


def propset_dict(propset):
    """Turn a propset list into a dictionary

    PropSet is an optional attribute on ObjectContent objects
    that are returned by the VMware API.

    You can read more about these at:
    http://pubs.vmware.com/vsphere-51/index.jsp
        #com.vmware.wssdk.apiref.doc/
            vmodl.query.PropertyCollector.ObjectContent.html

    :param propset: a property "set" from ObjectContent
    :return: dictionary representing property set
    """
    if propset is None:
        return {}

    #TODO(hartsocks): once support for Python 2.6 is dropped
    # change to {[(prop.name, prop.val) for prop in propset]}
    return dict([(prop.name, prop.val) for prop in propset])


def _select_datastore(data_stores, best_match, datastore_regex=None):
    """Find the most preferable datastore in a given RetrieveResult object.

    :param data_stores: a RetrieveResult object from vSphere API call
    :param best_match: the current best match for datastore
    :param datastore_regex: an optional regular expression to match names
    :return: datastore_ref, datastore_name, capacity, freespace
    """

    # data_stores is actually a RetrieveResult object from vSphere API call
    for obj_content in data_stores.objects:
        # the propset attribute "need not be set" by returning API
        if not hasattr(obj_content, 'propSet'):
            continue

        propdict = propset_dict(obj_content.propSet)
        # Local storage identifier vSphere doesn't support CIFS or
        # vfat for datastores, therefore filtered
        ds_type = propdict['summary.type']
        ds_name = propdict['summary.name']
        if ((ds_type == 'VMFS' or ds_type == 'NFS') and
                propdict.get('summary.accessible')):
            if datastore_regex is None or datastore_regex.match(ds_name):
                new_ds = DSRecord(
                    datastore=obj_content.obj,
                    name=ds_name,
                    capacity=propdict['summary.capacity'],
                    freespace=propdict['summary.freeSpace'])
                # favor datastores with more free space
                if new_ds.freespace > best_match.freespace:
                    best_match = new_ds

    return best_match


def get_datastore_ref_and_name(session, cluster=None, host=None,
                               datastore_regex=None):
    """Get the datastore list and choose the most preferable one."""
    if cluster is None and host is None:
        data_stores = session._call_method(vim_util, "get_objects",
                    "Datastore", ["summary.type", "summary.name",
                                  "summary.capacity", "summary.freeSpace",
                                  "summary.accessible"])
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

        if not datastore_ret:
            raise exception.DatastoreNotFound()
        data_store_mors = datastore_ret.ManagedObjectReference
        data_stores = session._call_method(vim_util,
                                "get_properties_for_a_collection_of_objects",
                                "Datastore", data_store_mors,
                                ["summary.type", "summary.name",
                                 "summary.capacity", "summary.freeSpace",
                                 "summary.accessible"])
    best_match = DSRecord(datastore=None, name=None,
                          capacity=None, freespace=0)
    while data_stores:
        best_match = _select_datastore(data_stores, best_match,
                                       datastore_regex)
        token = _get_token(data_stores)
        if not token:
            break
        data_stores = session._call_method(vim_util,
                                           "continue_to_get_objects",
                                           token)
    if best_match.datastore:
        return best_match
    if datastore_regex:
        raise exception.DatastoreNotFound(
            _("Datastore regex %s did not match any datastores")
            % datastore_regex.pattern)
    else:
        raise exception.DatastoreNotFound()


def get_vmdk_backed_disk_uuid(hardware_devices, volume_uuid):
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                "VirtualDiskFlatVer2BackingInfo" and
                volume_uuid in device.backing.fileName):
            return device.backing.uuid


def get_vmdk_backed_disk_device(hardware_devices, uuid):
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                "VirtualDiskFlatVer2BackingInfo" and
                device.backing.uuid == uuid):
            return device


def get_vmdk_volume_disk(hardware_devices, path=None):
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk"):
            if not path or path == device.backing.fileName:
                return device


def get_res_pool_ref(session, cluster, node_mo_id):
    """Get the resource pool."""
    if cluster is None:
        # With no cluster named, use the root resource pool.
        results = session._call_method(vim_util, "get_objects",
                                       "ResourcePool")
        _cancel_retrieve_if_necessary(session, results)
        # The 0th resource pool is always the root resource pool on both ESX
        # and vCenter.
        res_pool_ref = results.objects[0].obj
    else:
        if cluster.value == node_mo_id:
            # Get the root resource pool of the cluster
            res_pool_ref = session._call_method(vim_util,
                                                  "get_dynamic_property",
                                                  cluster,
                                                  "ClusterComputeResource",
                                                  "resourcePool")

    return res_pool_ref


def get_all_cluster_mors(session):
    """Get all the clusters in the vCenter."""
    try:
        results = session._call_method(vim_util, "get_objects",
                                        "ClusterComputeResource", ["name"])
        _cancel_retrieve_if_necessary(session, results)
        return results.objects

    except Exception as excep:
        LOG.warn(_("Failed to get cluster references %s") % excep)


def get_all_res_pool_mors(session):
    """Get all the resource pools in the vCenter."""
    try:
        results = session._call_method(vim_util, "get_objects",
                                             "ResourcePool")

        _cancel_retrieve_if_necessary(session, results)
        return results.objects
    except Exception as excep:
        LOG.warn(_("Failed to get resource pool references " "%s") % excep)


def get_dynamic_property_mor(session, mor_ref, attribute):
    """Get the value of an attribute for a given managed object."""
    return session._call_method(vim_util, "get_dynamic_property",
                                mor_ref, mor_ref._type, attribute)


def find_entity_mor(entity_list, entity_name):
    """Returns managed object ref for given cluster or resource pool name."""
    return [mor for mor in entity_list if (hasattr(mor, 'propSet') and
                                           mor.propSet[0].val == entity_name)]


def get_all_cluster_refs_by_name(session, path_list):
    """Get reference to the Cluster, ResourcePool with the path specified.

    The path is the display name. This can be the full path as well.
    The input will have the list of clusters and resource pool names
    """
    cls = get_all_cluster_mors(session)
    if not cls:
        return
    res = get_all_res_pool_mors(session)
    if not res:
        return
    path_list = [path.strip() for path in path_list]
    list_obj = []
    for entity_path in path_list:
        # entity_path could be unique cluster and/or resource-pool name
        res_mor = find_entity_mor(res, entity_path)
        cls_mor = find_entity_mor(cls, entity_path)
        cls_mor.extend(res_mor)
        for mor in cls_mor:
            list_obj.append((mor.obj, mor.propSet[0].val))
    return get_dict_mor(session, list_obj)


def get_dict_mor(session, list_obj):
    """The input is a list of objects in the form
    (manage_object,display_name)
    The managed object will be in the form
    { value = "domain-1002", _type = "ClusterComputeResource" }

    Output data format:
    dict_mors = {
                  'respool-1001': { 'cluster_mor': clusterMor,
                                    'res_pool_mor': resourcePoolMor,
                                    'name': display_name },
                  'domain-1002': { 'cluster_mor': clusterMor,
                                    'res_pool_mor': resourcePoolMor,
                                    'name': display_name },
                }
    """
    dict_mors = {}
    for obj_ref, path in list_obj:
        if obj_ref._type == "ResourcePool":
            # Get owner cluster-ref mor
            cluster_ref = get_dynamic_property_mor(session, obj_ref, "owner")
            dict_mors[obj_ref.value] = {'cluster_mor': cluster_ref,
                                        'res_pool_mor': obj_ref,
                                        'name': path,
                                        }
        else:
            # Get default resource pool of the cluster
            res_pool_ref = get_dynamic_property_mor(session,
                                                    obj_ref, "resourcePool")
            dict_mors[obj_ref.value] = {'cluster_mor': obj_ref,
                                        'res_pool_mor': res_pool_ref,
                                        'name': path,
                                        }
    return dict_mors


def get_mo_id_from_instance(instance):
    """Return the managed object ID from the instance.

    The instance['node'] will have the hypervisor_hostname field of the
    compute node on which the instance exists or will be provisioned.
    This will be of the form
    'respool-1001(MyResPoolName)'
    'domain-1001(MyClusterName)'
    """
    return instance['node'].partition('(')[0]


def get_vmdk_adapter_type(adapter_type):
    """Return the adapter type to be used in vmdk descriptor.

    Adapter type in vmdk descriptor is same for LSI-SAS & LSILogic
    because Virtual Disk Manager API does not recognize the newer controller
    types.
    """
    if adapter_type == "lsiLogicsas":
        vmdk_adapter_type = "lsiLogic"
    else:
        vmdk_adapter_type = adapter_type
    return vmdk_adapter_type
