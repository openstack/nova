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
import hashlib
import operator
import socket
import ssl

import six

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
from oslo_utils.versionutils import convert_version_to_int
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import pbm
from oslo_vmware import vim_util as vutil

import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi.session import StableMoRefProxy
from nova.virt.vmwareapi import vim_util

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

ALL_SUPPORTED_NETWORK_DEVICES = ['VirtualE1000', 'VirtualE1000e',
                                 'VirtualPCNet32', 'VirtualSriovEthernetCard',
                                 'VirtualVmxnet', 'VirtualVmxnet3']

CONTROLLER_TO_ADAPTER_TYPE = {
    "VirtualLsiLogicController": constants.DEFAULT_ADAPTER_TYPE,
    "VirtualBusLogicController": constants.ADAPTER_TYPE_BUSLOGIC,
    "VirtualIDEController": constants.ADAPTER_TYPE_IDE,
    "VirtualLsiLogicSASController": constants.ADAPTER_TYPE_LSILOGICSAS,
    "ParaVirtualSCSIController": constants.ADAPTER_TYPE_PARAVIRTUAL
}

# A simple cache for storing inventory folder references.
# Format: {inventory_path: folder_ref}
_FOLDER_PATH_REF_MAPPING = {}

# A cache for VM references. The key will be the VM name
# and the value is the VM reference. The VM name is unique. This
# is either the UUID of the instance or UUID-rescue in the case
# that this is a rescue VM. This is in order to prevent
# unnecessary communication with the backend.
_VM_REFS_CACHE = {}
_VM_VALUE_CACHE = collections.defaultdict(dict)

_HOST_RESERVATIONS_DEFAULT_KEY = '__default__'


class Limits(object):

    def __init__(self, limit=None, reservation=None,
                 shares_level=None, shares_share=None):
        """imits object holds instance limits for convenience."""
        self.limit = limit
        self.reservation = reservation
        self.shares_level = shares_level
        self.shares_share = shares_share

    def validate(self):
        if self.shares_level in ('high', 'normal', 'low'):
            if self.shares_share:
                reason = _("Share level '%s' cannot have share "
                           "configured") % self.shares_level
                raise exception.InvalidInput(reason=reason)
            return
        if self.shares_level == 'custom':
            return
        if self.shares_level:
            reason = _("Share '%s' is not supported") % self.shares_level
            raise exception.InvalidInput(reason=reason)

    def has_limits(self):
        return bool(self.limit or
                    self.reservation or
                    self.shares_level)


class ExtraSpecs(object):

    def __init__(self, cpu_limits=None, hw_version=None,
                 storage_policy=None, cores_per_socket=None,
                 memory_limits=None, disk_io_limits=None,
                 vif_limits=None, hv_enabled=None, firmware=None,
                 hw_video_ram=None, numa_prefer_ht=None,
                 numa_vcpu_max_per_virtual_node=None,
                 migration_data_timeout=None):
        """ExtraSpecs object holds extra_specs for the instance."""
        self.cpu_limits = cpu_limits or Limits()
        self.memory_limits = memory_limits or Limits()
        self.disk_io_limits = disk_io_limits or Limits()
        self.vif_limits = vif_limits or Limits()
        self.hw_version = hw_version or CONF.vmware.default_hw_version
        self.storage_policy = storage_policy
        self.cores_per_socket = cores_per_socket
        self.hv_enabled = hv_enabled
        self.firmware = firmware
        self.hw_video_ram = hw_video_ram
        self.numa_prefer_ht = numa_prefer_ht
        self.numa_vcpu_max_per_virtual_node = numa_vcpu_max_per_virtual_node
        self.migration_data_timeout = migration_data_timeout


class HistoryCollectorItems(six.Iterator):

    def __init__(self, session, history_collector, read_page_method,
                 reverse_page_order=False, max_page_size=10,
                 page_sort_key_func=None):
        self.session = session
        self.history_collector = history_collector
        self.read_page_method = read_page_method
        self.reverse_page_order = reverse_page_order
        self.max_page_size = max_page_size
        self.page_sort_key_func = page_sort_key_func

    def __iter__(self):
        self._latest_page_read = False
        self._page_items = None

        if self.reverse_page_order:
            self.session._call_method(self.session.vim,
                                      "ResetCollector",
                                      self.history_collector)
        else:
            self.session._call_method(self.session.vim,
                                      "RewindCollector",
                                      self.history_collector)

        return self

    def __next__(self):
        if not self._page_items:
            self._load_page()

        if not self._page_items:
            raise StopIteration
        else:
            return self._page_items.pop(0)

    def _load_page(self):
        if self.reverse_page_order and not self._latest_page_read:
            self._load_latest_page()

        if not self._page_items:
            self._page_items = self.session._call_method(
                self.session.vim, self.read_page_method,
                self.history_collector, maxCount=self.max_page_size)

        if self._page_items and self.page_sort_key_func:
            self._page_items.sort(reverse=self.reverse_page_order,
                                  key=self.page_sort_key_func)

    def _load_latest_page(self):
        self._latest_page_read = True
        latest_page = vutil.get_object_property(self.session.vim,
                                                self.history_collector,
                                                "latestPage")

        self._page_items = vim_util.get_array_items(latest_page)

    def destroy_collector(self):
        if self.history_collector:
            self.session._call_method(self.session.vim,
                                      "DestroyCollector",
                                      self.history_collector)


class TaskHistoryCollectorItems(HistoryCollectorItems):
    def __init__(self, session, task_filter_spec, reverse_page_order=False,
                 max_page_size=10):
        task_collector = session._call_method(
            session.vim,
            "CreateCollectorForTasks",
            session.vim.service_content.taskManager,
            filter=task_filter_spec)
        read_page_method = ("ReadPreviousTasks" if reverse_page_order
                            else "ReadNextTasks")
        page_sort_key_func = operator.attrgetter('queueTime')
        super(TaskHistoryCollectorItems, self).__init__(session,
                                                        task_collector,
                                                        read_page_method,
                                                        reverse_page_order,
                                                        max_page_size,
                                                        page_sort_key_func)

    def __del__(self):
        self.destroy_collector()


class EventHistoryCollectorItems(HistoryCollectorItems):
    def __init__(self, session, event_filter_spec, reverse_page_order=False,
                 max_page_size=10):
        event_collector = session._call_method(
            session.vim,
            "CreateCollectorForEvents",
            session.vim.service_content.eventManager,
            filter=event_filter_spec)
        read_page_method = ("ReadPreviousEvents" if reverse_page_order
                            else "ReadNextEvents")
        page_sort_key_func = operator.attrgetter('createdTime')
        super(EventHistoryCollectorItems, self).__init__(session,
                                                         event_collector,
                                                         read_page_method,
                                                         reverse_page_order,
                                                         max_page_size,
                                                         page_sort_key_func)

    def __del__(self):
        self.destroy_collector()


def vm_value_cache_reset():
    global _VM_VALUE_CACHE
    _VM_VALUE_CACHE = {}


def vm_value_cache_delete(id):
    _VM_VALUE_CACHE.pop(id, None)


def vm_value_cache_update(id, change_name, val):
    _VM_VALUE_CACHE[id][change_name] = val


def vm_value_cache_get(id):
    return _VM_VALUE_CACHE.get(id)


def vm_refs_cache_reset():
    global _VM_REFS_CACHE
    _VM_REFS_CACHE = {}


def vm_ref_cache_delete(id_):
    _VM_REFS_CACHE.pop(id_, None)


def vm_ref_cache_update(id_, vm_ref):
    _VM_REFS_CACHE[id_] = vm_ref


def vm_ref_cache_get(id_):
    return _VM_REFS_CACHE.get(id_)


# the config key which stores the VNC port
VNC_CONFIG_KEY = 'config.extraConfig["RemoteDisplay.vnc.port"]'

VmdkInfo = collections.namedtuple('VmdkInfo', ['path', 'adapter_type',
                                               'disk_type',
                                               'capacity_in_bytes',
                                               'device'])


def _iface_id_option_value(client_factory, iface_id, port_index):
    opt = client_factory.create('ns0:OptionValue')
    opt.key = "nvp.iface-id.%d" % port_index
    opt.value = iface_id
    return opt


def _get_allocation_info(client_factory, limits, allocation_type):
    allocation = client_factory.create(allocation_type)
    if limits.limit:
        allocation.limit = limits.limit
    else:
        # Set as 'unlimited'
        allocation.limit = -1
    if limits.reservation:
        allocation.reservation = limits.reservation
    else:
        allocation.reservation = 0
    shares = client_factory.create('ns0:SharesInfo')
    if limits.shares_level:
        shares.level = limits.shares_level
        if (shares.level == 'custom' and
            limits.shares_share):
            shares.shares = limits.shares_share
        else:
            shares.shares = 0
    else:
        shares.level = 'normal'
        shares.shares = 0
    # The VirtualEthernetCardResourceAllocation has 'share' instead of
    # 'shares'.
    if hasattr(allocation, 'share'):
        allocation.share = shares
    else:
        allocation.shares = shares
    return allocation


def append_vif_infos_to_config_spec(client_factory, config_spec,
                                    vif_infos, vif_limits, index=0):

    if not hasattr(config_spec, 'deviceChange') or \
        not config_spec.deviceChange:
        config_spec.deviceChange = []
    for offset, vif_info in enumerate(vif_infos):
        vif_spec = _create_vif_spec(client_factory, vif_info, vif_limits,
            offset)
        config_spec.deviceChange.append(vif_spec)

    if not hasattr(config_spec, 'extraConfig') or \
        not config_spec.extraConfig:
        config_spec.extraConfig = []
    port_index = index
    for vif_info in vif_infos:
        if vif_info['iface_id']:
            config_spec.extraConfig.append(
                    _iface_id_option_value(client_factory,
                                           vif_info['iface_id'],
                                           port_index))
            port_index += 1


def get_vm_create_spec(client_factory, instance, data_store_name,
                       vif_infos, extra_specs,
                       os_type=constants.DEFAULT_OS_TYPE,
                       profile_spec=None, metadata=None, vm_name=None):
    """Builds the VM Create spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    config_spec.name = vm_name or instance.uuid
    config_spec.guestId = os_type
    # The name is the unique identifier for the VM.
    config_spec.instanceUuid = instance.uuid
    if metadata:
        config_spec.annotation = metadata
    # set the Hardware version
    config_spec.version = extra_specs.hw_version

    # Allow nested hypervisor instances to host 64 bit VMs.
    if (os_type in ("vmkernel5Guest", "vmkernel6Guest",
                    "windowsHyperVGuest")) or (
        extra_specs.hv_enabled == "True"):
        config_spec.nestedHVEnabled = "True"

    # Append the profile spec
    if profile_spec:
        config_spec.vmProfile = [profile_spec]

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
    if extra_specs.cores_per_socket:
        config_spec.numCoresPerSocket = int(extra_specs.cores_per_socket)
    # NOTE(jkulik): this only works with 6.7 and newer
    if int(instance.vcpus) > 128:
        flags = client_factory.create('ns0:VirtualMachineFlagInfo')
        flags.vvtdEnabled = True
        flags.virtualMmuUsage = 'automatic'
        config_spec.flags = flags
    config_spec.memoryMB = int(instance.memory_mb)

    # Configure cpu information
    if extra_specs.cpu_limits.has_limits():
        config_spec.cpuAllocation = _get_allocation_info(
            client_factory, extra_specs.cpu_limits,
            'ns0:ResourceAllocationInfo')

    # Configure memory information
    if extra_specs.memory_limits.has_limits():
        config_spec.memoryAllocation = _get_allocation_info(
            client_factory, extra_specs.memory_limits,
            'ns0:ResourceAllocationInfo')

    if extra_specs.firmware:
        config_spec.firmware = extra_specs.firmware

    devices = []
    serial_port_spec = create_serial_port_spec(client_factory)
    if serial_port_spec:
        devices.append(serial_port_spec)

    virtual_device_config_spec = create_video_card_spec(client_factory,
                                                        extra_specs)
    if virtual_device_config_spec:
        devices.append(virtual_device_config_spec)

    config_spec.deviceChange = devices

    # add vm-uuid and iface-id.x values for Neutron
    extra_config = []
    opt = client_factory.create('ns0:OptionValue')
    opt.key = "nvp.vm-uuid"
    opt.value = instance.uuid
    extra_config.append(opt)

    # enable to provide info needed by udev to generate /dev/disk/by-id
    opt = client_factory.create('ns0:OptionValue')
    opt.key = "disk.EnableUUID"
    opt.value = 'true'
    extra_config.append(opt)

    if (CONF.vmware.console_delay_seconds and
        CONF.vmware.console_delay_seconds > 0):
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'keyboard.typematicMinDelay'
        opt.value = CONF.vmware.console_delay_seconds * 1000000
        extra_config.append(opt)

    if CONF.vmware.smbios_asset_tag:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'smbios.assetTag'
        opt.value = CONF.vmware.smbios_asset_tag
        extra_config.append(opt)

    if CONF.vmware.mirror_instance_logs_to_syslog:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'vmx.log.syslogID'
        opt.value = instance.uuid + '_vmx_log'
        extra_config.append(opt)

    # big VMs need to prefer HT threads to stay in NUMA nodes
    if extra_specs.numa_prefer_ht is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'numa.vcpu.preferHT'
        opt.value = extra_specs.numa_prefer_ht
        extra_config.append(opt)

    # single- & half-NUMA-node VMs get more than one node without this setting
    if extra_specs.numa_vcpu_max_per_virtual_node is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'numa.autosize.vcpu.maxPerVirtualNode'
        opt.value = extra_specs.numa_vcpu_max_per_virtual_node
        extra_config.append(opt)

    # big VMs need more time to settle to make reconfigures possible after they
    # ran for some time
    if extra_specs.migration_data_timeout is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'migration.dataTimeout'
        opt.value = extra_specs.migration_data_timeout
        extra_config.append(opt)

    config_spec.extraConfig = extra_config

    append_vif_infos_to_config_spec(client_factory, config_spec,
                                    vif_infos, extra_specs.vif_limits)

    # Set the VM to be 'managed' by 'OpenStack'
    managed_by = client_factory.create('ns0:ManagedByInfo')
    managed_by.extensionKey = constants.EXTENSION_KEY
    managed_by.type = constants.EXTENSION_TYPE_INSTANCE
    config_spec.managedBy = managed_by

    return config_spec


def create_video_card_spec(client_factory, extra_specs):
    if extra_specs.hw_video_ram:
        video_card = client_factory.create('ns0:VirtualMachineVideoCard')
        video_card.videoRamSizeInKB = extra_specs.hw_video_ram
        video_card.key = -1
        virtual_device_config_spec = client_factory.create(
            'ns0:VirtualDeviceConfigSpec')
        virtual_device_config_spec.operation = "add"
        virtual_device_config_spec.device = video_card
        return virtual_device_config_spec


def create_serial_port_spec(client_factory):
    """Creates config spec for serial port."""
    if not CONF.vmware.serial_port_service_uri:
        return

    backing = client_factory.create('ns0:VirtualSerialPortURIBackingInfo')
    backing.direction = "server"
    backing.serviceURI = CONF.vmware.serial_port_service_uri
    backing.proxyURI = CONF.vmware.serial_port_proxy_uri

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = CONF.vmware.serial_port_connected_default
    connectable_spec.allowGuestControl = True
    connectable_spec.connected = CONF.vmware.serial_port_connected_default

    serial_port = client_factory.create('ns0:VirtualSerialPort')
    serial_port.connectable = connectable_spec
    serial_port.backing = backing
    # we are using unique negative integers as temporary keys
    serial_port.key = -2
    serial_port.yieldOnPoll = True
    dev_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    dev_spec.operation = "add"
    dev_spec.device = serial_port
    return dev_spec


def get_vm_boot_spec(client_factory, device, is_efi=False):
    """Returns updated boot settings for the instance.

    The boot order for the instance will be changed to have the
    input device as the boot disk.

    If "is_efi" is True, "quickBoot" will be disabled for the VM so it can
    actually see the rescue disk during the boot decision.
    """
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    boot_disk = client_factory.create(
        'ns0:VirtualMachineBootOptionsBootableDiskDevice')
    boot_disk.deviceKey = device.key
    boot_options = client_factory.create('ns0:VirtualMachineBootOptions')
    boot_options.bootOrder = [boot_disk]
    config_spec.bootOptions = boot_options

    if is_efi:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'efi.quickBoot.enabled'
        opt.value = 'FALSE'
        config_spec.extraConfig = [opt]

    return config_spec


def get_vm_resize_spec(client_factory, vcpus, memory_mb, extra_specs,
                       metadata=None):
    """Provides updates for a VM spec."""
    resize_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    resize_spec.numCPUs = vcpus
    resize_spec.memoryMB = memory_mb
    resize_spec.cpuAllocation = _get_allocation_info(
        client_factory, extra_specs.cpu_limits,
        'ns0:ResourceAllocationInfo')
    resize_spec.memoryAllocation = _get_allocation_info(
        client_factory, extra_specs.memory_limits,
        'ns0:ResourceAllocationInfo')
    # NOTE(jkulik) We used to set this setting instead of `memoryAllocation`,
    # so we need to deconfigure it on VMs created before the patch adding
    # `memoryAllocation` support on resize.
    resize_spec.memoryReservationLockedToMax = False

    if extra_specs.cores_per_socket:
        resize_spec.numCoresPerSocket = int(extra_specs.cores_per_socket)
    # NOTE(jkulik): this only works with 6.7 and newer
    if int(vcpus) > 128:
        flags = client_factory.create('ns0:VirtualMachineFlagInfo')
        flags.vvtdEnabled = True
        flags.virtualMmuUsage = 'automatic'
        resize_spec.flags = flags

    extra_config = []
    # big VMs need to prefer HT threads to stay in NUMA nodes
    if extra_specs.numa_prefer_ht is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'numa.vcpu.preferHT'
        opt.value = extra_specs.numa_prefer_ht
        extra_config.append(opt)

    # single- & half-NUMA-node VMs get more than one node without this setting
    if extra_specs.numa_vcpu_max_per_virtual_node is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'numa.autosize.vcpu.maxPerVirtualNode'
        opt.value = extra_specs.numa_vcpu_max_per_virtual_node
        extra_config.append(opt)

    # big VMs need more time to settle to make reconfigures possible after they
    # ran for some time
    if extra_specs.migration_data_timeout is not None:
        opt = client_factory.create('ns0:OptionValue')
        opt.key = 'migration.dataTimeout'
        opt.value = extra_specs.migration_data_timeout
        extra_config.append(opt)

    resize_spec.extraConfig = extra_config

    if metadata:
        resize_spec.annotation = metadata
    return resize_spec


def create_controller_spec(client_factory, key,
                           adapter_type=constants.DEFAULT_ADAPTER_TYPE,
                           bus_number=0):
    """Builds a Config Spec for the LSI or Bus Logic Controller's addition
    which acts as the controller for the virtual hard disk to be attached
    to the VM.
    """
    # Create a controller for the Virtual Hard Disk
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "add"
    if adapter_type == constants.ADAPTER_TYPE_BUSLOGIC:
        virtual_controller = client_factory.create(
                                'ns0:VirtualBusLogicController')
    elif adapter_type == constants.ADAPTER_TYPE_LSILOGICSAS:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicSASController')
    elif adapter_type == constants.ADAPTER_TYPE_PARAVIRTUAL:
        virtual_controller = client_factory.create(
                                'ns0:ParaVirtualSCSIController')
    else:
        virtual_controller = client_factory.create(
                                'ns0:VirtualLsiLogicController')
    virtual_controller.key = key
    virtual_controller.busNumber = bus_number
    virtual_controller.sharedBus = "noSharing"
    virtual_device_config.device = virtual_controller
    return virtual_device_config


def convert_vif_model(name):
    """Converts standard VIF_MODEL types to the internal VMware ones."""
    if name == network_model.VIF_MODEL_E1000:
        return 'VirtualE1000'
    if name == network_model.VIF_MODEL_E1000E:
        return 'VirtualE1000e'
    if name == network_model.VIF_MODEL_PCNET:
        return 'VirtualPCNet32'
    if name == network_model.VIF_MODEL_SRIOV:
        return 'VirtualSriovEthernetCard'
    if name == network_model.VIF_MODEL_VMXNET:
        return 'VirtualVmxnet'
    if name == network_model.VIF_MODEL_VMXNET3:
        return 'VirtualVmxnet3'
    if name not in ALL_SUPPORTED_NETWORK_DEVICES:
        msg = _('%s is not supported.') % name
        raise exception.Invalid(msg)
    return name


def _create_vif_spec(client_factory, vif_info, vif_limits=None, offset=0):
    """Builds a config spec for the addition of a new network
    adapter to the VM.
    """
    network_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    network_spec.operation = "add"

    # Keep compatible with other Hyper vif model parameter.
    vif_info['vif_model'] = convert_vif_model(vif_info['vif_model'])

    vif = 'ns0:' + vif_info['vif_model']
    net_device = client_factory.create(vif)

    # NOTE(asomya): Only works on ESXi if the portgroup binding is set to
    # ephemeral. Invalid configuration if set to static and the NIC does
    # not come up on boot if set to dynamic.
    mac_address = vif_info['mac_address']
    set_net_device_backing(client_factory, net_device, vif_info)
    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = True
    connectable_spec.connected = True

    net_device.connectable = connectable_spec

    # The Server assigns a Key to the device. Here we pass a -ve temporary key.
    # -ve because actual keys are +ve numbers and we don't
    # want a clash with the key that server might associate with the device
    # We add a potential offset, so that multiple nics do not get the same key
    net_device.key = -47 + offset
    net_device.addressType = "manual"
    net_device.macAddress = mac_address
    net_device.wakeOnLanEnabled = True

    # vnic limits are only supported from version 6.0
    if vif_limits and vif_limits.has_limits():
        if hasattr(net_device, 'resourceAllocation'):
            net_device.resourceAllocation = _get_allocation_info(
                client_factory, vif_limits,
                'ns0:VirtualEthernetCardResourceAllocation')
        else:
            msg = _('Limits only supported from vCenter 6.0 and above')
            raise exception.Invalid(msg)

    network_spec.device = net_device
    return network_spec


def set_net_device_backing(client_factory, net_device, vif_info):
    network_ref = vif_info['network_ref']
    network_name = vif_info['network_name']
    backing = None
    if network_ref and network_ref['type'] == 'OpaqueNetwork':
        backing = client_factory.create(
                'ns0:VirtualEthernetCardOpaqueNetworkBackingInfo')
        backing.opaqueNetworkId = network_ref['network-id']
        backing.opaqueNetworkType = network_ref['network-type']
        # Configure externalId
        if network_ref['use-external-id']:
            # externalId is only supported from vCenter 6.0 onwards
            if hasattr(net_device, 'externalId'):
                net_device.externalId = vif_info['iface_id']
            else:
                dp = client_factory.create('ns0:DynamicProperty')
                dp.name = "__externalId__"
                dp.val = vif_info['iface_id']
                net_device.dynamicProperty = [dp]
    elif (network_ref and
            network_ref['type'] == "DistributedVirtualPortgroup"):
        backing = client_factory.create(
                'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
        portgroup = client_factory.create(
                    'ns0:DistributedVirtualSwitchPortConnection')
        portgroup.switchUuid = network_ref['dvsw']
        portgroup.portgroupKey = network_ref['dvpg']
        if 'dvs_port_key' in network_ref:
            portgroup.portKey = network_ref['dvs_port_key']
        backing.port = portgroup
    else:
        backing = client_factory.create(
                  'ns0:VirtualEthernetCardNetworkBackingInfo')
        backing.deviceName = network_name
    net_device.backing = backing


def get_network_attach_config_spec(client_factory, vif_info, index,
                                   vif_limits=None):
    """Builds the vif attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    append_vif_infos_to_config_spec(client_factory, config_spec,
                                    [vif_info], vif_limits, index)

    return config_spec


def get_network_detach_config_spec(client_factory, device, port_index):
    """Builds the vif detach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    virtual_device_config = client_factory.create(
                            'ns0:VirtualDeviceConfigSpec')
    virtual_device_config.operation = "remove"
    virtual_device_config.device = device
    config_spec.deviceChange = [virtual_device_config]
    # If a key is already present then it cannot be deleted, only updated.
    # This enables us to reuse this key if there is an additional
    # attachment. The keys need to be preserved. This is due to the fact
    # that there is logic on the ESX that does the network wiring
    # according to these values. If they are changed then this will
    # break networking to and from the interface.
    config_spec.extraConfig = [_iface_id_option_value(client_factory,
                                                      'free',
                                                      port_index)]
    return config_spec


def update_vif_spec(client_factory, vif_info, device):
    """Updates the backing for the VIF spec."""
    network_spec = client_factory.create('ns0:VirtualDeviceConfigSpec')
    network_spec.operation = 'edit'
    network_ref = vif_info['network_ref']
    network_name = vif_info['network_name']
    if network_ref and network_ref['type'] == 'OpaqueNetwork':
        backing = client_factory.create(
                'ns0:VirtualEthernetCardOpaqueNetworkBackingInfo')
        backing.opaqueNetworkId = network_ref['network-id']
        backing.opaqueNetworkType = network_ref['network-type']
        # Configure externalId
        if network_ref['use-external-id']:
            if hasattr(device, 'externalId'):
                device.externalId = vif_info['iface_id']
            else:
                dp = client_factory.create('ns0:DynamicProperty')
                dp.name = "__externalId__"
                dp.val = vif_info['iface_id']
                device.dynamicProperty = [dp]
    elif (network_ref and
            network_ref['type'] == "DistributedVirtualPortgroup"):
        backing = client_factory.create(
                'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
        portgroup = client_factory.create(
                    'ns0:DistributedVirtualSwitchPortConnection')
        portgroup.switchUuid = network_ref['dvsw']
        portgroup.portgroupKey = network_ref['dvpg']
        backing.port = portgroup
    else:
        backing = client_factory.create(
                  'ns0:VirtualEthernetCardNetworkBackingInfo')
        backing.deviceName = network_name
    device.backing = backing
    network_spec.device = device
    return network_spec


def get_storage_profile_spec(session, storage_policy):
    """Gets the vm profile spec configured for storage policy."""
    profile_id = pbm.get_profile_id_by_name(session, storage_policy)
    if profile_id:
        client_factory = session.vim.client.factory
        storage_profile_spec = client_factory.create(
            'ns0:VirtualMachineDefinedProfileSpec')
        storage_profile_spec.profileId = profile_id.uniqueId
        return storage_profile_spec


def get_vmdk_attach_config_spec(client_factory,
                                disk_type=constants.DEFAULT_DISK_TYPE,
                                file_path=None,
                                disk_size=None,
                                linked_clone=False,
                                controller_key=None,
                                unit_number=None,
                                device_name=None,
                                disk_io_limits=None,
                                profile_id=None):
    """Builds the vmdk attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = _create_virtual_disk_spec(client_factory,
                                controller_key, disk_type, file_path,
                                disk_size, linked_clone,
                                unit_number, device_name, disk_io_limits,
                                profile_id=profile_id)

    device_config_spec.append(virtual_device_config_spec)

    config_spec.deviceChange = device_config_spec
    return config_spec


def get_cdrom_attach_config_spec(client_factory,
                                 datastore,
                                 file_path,
                                 controller_key,
                                 cdrom_unit_number,
                                 cdrom_key=-1):
    """Builds and returns the cdrom attach config spec."""
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')

    device_config_spec = []
    virtual_device_config_spec = create_virtual_cdrom_spec(client_factory,
                                                           datastore,
                                                           controller_key,
                                                           file_path,
                                                           cdrom_unit_number,
                                                           cdrom_key=cdrom_key)

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


def create_extra_config(client_factory, extra_opts):
    """Turn the given dict extra_opts into a list of OptionValue

    The returned list can be used to set the extraConfig attribute of a
    VirtualMachineConfigSpec.
    """
    extra_config = []
    for key, value in extra_opts.items():
        opt = client_factory.create('ns0:OptionValue')
        opt.key = key
        opt.value = value
        extra_config.append(opt)

    return extra_config


def _get_device_capacity(device):
    # Devices pre-vSphere-5.5 only reports capacityInKB, which has
    # rounding inaccuracies. Use that only if the more accurate
    # attribute is absent.
    if hasattr(device, 'capacityInBytes'):
        return device.capacityInBytes
    else:
        return device.capacityInKB * units.Ki


def _get_device_disk_type(device):
    if getattr(device.backing, 'thinProvisioned', False):
        return constants.DISK_TYPE_THIN
    else:
        if getattr(device.backing, 'eagerlyScrub', False):
            return constants.DISK_TYPE_EAGER_ZEROED_THICK
        else:
            return constants.DEFAULT_DISK_TYPE


def get_hardware_devices(session, vm_ref):
    hardware_devices = session._call_method(vutil,
                                            "get_object_property",
                                            vm_ref,
                                            "config.hardware.device")
    return vim_util.get_array_items(hardware_devices)


def _in_boot_order(disk1, disk2):
    return (disk2.controllerKey > disk1.controllerKey or
        disk2.controllerKey == disk2.controllerKey and
        disk2.unitNumber > disk1.unitNumber)


def get_hardware_devices_by_type(session, vm_ref):
    nics = {}
    controllers = {}
    disks = {}
    cdroms = {}
    swap = None
    ephemeral = []
    first_device = None

    for device in get_hardware_devices(session, vm_ref):
        device_type = device.__class__.__name__
        if device_type in ALL_SUPPORTED_NETWORK_DEVICES:
            mac_address = getattr(device, 'macAddress', None)
            if not mac_address:
                LOG.warning("Could not ge mac address of NIC {}", device.key)
                continue
            if mac_address in nics:
                LOG.warning("Multiple NICs with the same MAC")
                continue

            nics[mac_address] = device
        elif device_type in CONTROLLER_TO_ADAPTER_TYPE:
            controllers[int(device.key)] = device
        elif device_type == "VirtualDisk":
            backing_type = device.backing.__class__.__name__
            if backing_type == "VirtualDiskFlatVer2BackingInfo":
                if "swap" in device.backing.fileName:
                    swap = device
                elif "ephemeral" in device.backing.fileName:
                    ephemeral.append(device)
                else:
                    if not first_device or not _in_boot_order(first_device,
                                                              device):
                        first_device = device
                    uuid = getattr(device.backing, "uuid", None)
                    if not uuid:
                        LOG.warning("Failed to get uuid from device {}",
                                    device.key)
                        continue
                    disks[uuid.lower()] = device
            elif backing_type == "VirtualDiskRawDiskMappingVer1BackingInfo":
                disks[device.backing.lunUuid.lower()] = device
        elif device_type == "VirtualCdrom":
            cdroms[int(device.key)] = device

    return {
        "nics": nics,
        "controllers": controllers,
        "swap": swap,
        "ephemeral": ephemeral,
        "disks": disks,
        "cdroms": cdroms,
        "root_device": first_device
    }


def get_vmdk_info(session, vm_ref):
    """Returns information for the first VMDK attached to the given VM."""
    hardware_devices = get_hardware_devices(session, vm_ref)
    vmdk_file_path = None
    vmdk_controller_key = None
    disk_type = None
    capacity_in_bytes = 0

    first_device = None

    adapter_type_dict = {}
    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if device.backing.__class__.__name__ == \
                    "VirtualDiskFlatVer2BackingInfo":
                if first_device is None or not _in_boot_order(first_device,
                                                              device):
                    first_device = device
        elif device.__class__.__name__ in CONTROLLER_TO_ADAPTER_TYPE:
            adapter_type_dict[device.key] = CONTROLLER_TO_ADAPTER_TYPE[
                device.__class__.__name__]

    if first_device:
        vmdk_file_path = first_device.backing.fileName
        capacity_in_bytes = _get_device_capacity(first_device)
        vmdk_controller_key = first_device.controllerKey
        disk_type = _get_device_disk_type(first_device)

    adapter_type = adapter_type_dict.get(vmdk_controller_key)
    return VmdkInfo(vmdk_file_path, adapter_type, disk_type,
                    capacity_in_bytes, first_device)


scsi_controller_classes = {
    'ParaVirtualSCSIController': constants.ADAPTER_TYPE_PARAVIRTUAL,
    'VirtualLsiLogicController': constants.DEFAULT_ADAPTER_TYPE,
    'VirtualLsiLogicSASController': constants.ADAPTER_TYPE_LSILOGICSAS,
    'VirtualBusLogicController': constants.ADAPTER_TYPE_BUSLOGIC,
}


def get_scsi_adapter_type(hardware_devices):
    """Selects a proper iscsi adapter type from the existing
       hardware devices
    """
    for device in hardware_devices:
        if device.__class__.__name__ in scsi_controller_classes:
            # find the controllers which still have available slots
            if len(device.device) < constants.SCSI_MAX_CONNECT_NUMBER:
                # return the first match one
                return scsi_controller_classes[device.__class__.__name__]
    raise exception.StorageError(
        reason=_("Unable to find iSCSI Target"))


def _find_controller_slot(controller_keys, taken, max_unit_number):
    for controller_key in controller_keys:
        for unit_number in range(max_unit_number):
            if unit_number not in taken.get(controller_key, []):
                return controller_key, unit_number


def _is_ide_controller(device):
    return device.__class__.__name__ == 'VirtualIDEController'


def _is_scsi_controller(device):
    return device.__class__.__name__ in ['VirtualLsiLogicController',
                                         'VirtualLsiLogicSASController',
                                         'VirtualBusLogicController',
                                         'ParaVirtualSCSIController']


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


def _get_bus_number_for_scsi_controller(devices):
    """Return usable bus number when create new SCSI controller."""
    # Every SCSI controller will take a unique bus number
    taken = [dev.busNumber for dev in devices if _is_scsi_controller(dev)]
    # The max bus number for SCSI controllers is 3
    for i in range(constants.SCSI_MAX_CONTROLLER_NUMBER):
        if i not in taken:
            return i
    msg = _('Only %d SCSI controllers are allowed to be '
            'created on this instance.') % constants.SCSI_MAX_CONTROLLER_NUMBER
    raise vexc.VMwareDriverException(msg)


def allocate_controller_key_and_unit_number(client_factory, devices,
                                            adapter_type):
    """This function inspects the current set of hardware devices and returns
    controller_key and unit_number that can be used for attaching a new virtual
    disk to adapter with the given adapter_type.
    """
    taken = _find_allocated_slots(devices)

    ret = None
    if adapter_type == constants.ADAPTER_TYPE_IDE:
        ide_keys = [dev.key for dev in devices if _is_ide_controller(dev)]
        ret = _find_controller_slot(ide_keys, taken, 2)
    elif adapter_type in constants.SCSI_ADAPTER_TYPES:
        scsi_keys = [dev.key for dev in devices if _is_scsi_controller(dev)]
        ret = _find_controller_slot(scsi_keys, taken, 16)
    if ret:
        return ret[0], ret[1], None

    # create new controller with the specified type and return its spec
    controller_key = -101

    # Get free bus number for new SCSI controller.
    bus_number = 0
    if adapter_type in constants.SCSI_ADAPTER_TYPES:
        bus_number = _get_bus_number_for_scsi_controller(devices)

    controller_spec = create_controller_spec(client_factory, controller_key,
                                             adapter_type, bus_number)
    return controller_key, 0, controller_spec


def get_rdm_disk(hardware_devices, uuid):
    """Gets the RDM disk key."""
    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
            device.backing.__class__.__name__ ==
                "VirtualDiskRawDiskMappingVer1BackingInfo" and
                device.backing.lunUuid == uuid):
            return device


def get_vmdk_create_spec(client_factory, size_in_kb,
                         adapter_type=constants.DEFAULT_ADAPTER_TYPE,
                         disk_type=constants.DEFAULT_DISK_TYPE):
    """Builds the virtual disk create spec."""
    create_vmdk_spec = client_factory.create('ns0:FileBackedVirtualDiskSpec')
    create_vmdk_spec.adapterType = get_vmdk_adapter_type(adapter_type)
    create_vmdk_spec.diskType = disk_type
    create_vmdk_spec.capacityKb = size_in_kb
    return create_vmdk_spec


def create_virtual_cdrom_spec(client_factory,
                              datastore,
                              controller_key,
                              file_path,
                              cdrom_unit_number,
                              cdrom_key=-1,
                              cdrom_device_backing=None):
    """Builds spec for the creation of a new Virtual CDROM to the VM."""
    config_spec = client_factory.create(
        'ns0:VirtualDeviceConfigSpec')
    config_spec.operation = "edit" if cdrom_key > -1 else "add"

    cdrom = client_factory.create('ns0:VirtualCdrom')

    if not cdrom_device_backing and file_path:
        cdrom_device_backing = client_factory.create(
            'ns0:VirtualCdromIsoBackingInfo')
        cdrom_device_backing.datastore = datastore
        cdrom_device_backing.fileName = file_path

    cdrom.backing = cdrom_device_backing
    cdrom.controllerKey = controller_key
    cdrom.unitNumber = cdrom_unit_number
    cdrom.key = cdrom_key

    connectable_spec = client_factory.create('ns0:VirtualDeviceConnectInfo')
    connectable_spec.startConnected = True
    connectable_spec.allowGuestControl = False
    connectable_spec.connected = cdrom_device_backing is not None

    cdrom.connectable = connectable_spec

    config_spec.device = cdrom
    return config_spec


def _create_virtual_disk_spec(client_factory, controller_key,
                              disk_type=constants.DEFAULT_DISK_TYPE,
                              file_path=None,
                              disk_size=None,
                              linked_clone=False,
                              unit_number=None,
                              device_name=None,
                              disk_io_limits=None,
                              profile_id=None):
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
        if disk_type == constants.DISK_TYPE_THIN:
            disk_file_backing.thinProvisioned = True
        else:
            if disk_type == constants.DISK_TYPE_EAGER_ZEROED_THICK:
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

    if disk_io_limits and disk_io_limits.has_limits():
        virtual_disk.storageIOAllocation = _get_allocation_info(
            client_factory, disk_io_limits,
            'ns0:StorageIOAllocationInfo')

    virtual_device_config.device = virtual_disk

    if profile_id:
        disk_profile = \
            client_factory.create('ns0:VirtualMachineDefinedProfileSpec')
        disk_profile.profileId = profile_id
        virtual_device_config.profile = [disk_profile]

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
                  power_on=False, snapshot=None, template=False, config=None):
    """Builds the VM clone spec."""
    clone_spec = client_factory.create('ns0:VirtualMachineCloneSpec')
    clone_spec.location = location
    clone_spec.powerOn = power_on
    if snapshot:
        clone_spec.snapshot = snapshot
    if config is not None:
        clone_spec.config = config
    clone_spec.template = template
    return clone_spec


def relocate_vm_spec(client_factory, res_pool=None, datastore=None, host=None,
                     disk_move_type="moveAllDiskBackingsAndAllowSharing",
                     devices=None, folder=None):
    rel_spec = client_factory.create('ns0:VirtualMachineRelocateSpec')
    rel_spec.datastore = datastore
    rel_spec.host = host
    rel_spec.folder = folder
    rel_spec.pool = res_pool
    rel_spec.diskMoveType = disk_move_type
    if devices is not None:
        rel_spec.deviceChange = devices
    return rel_spec


def relocate_vm(session, vm_ref, res_pool=None, datastore=None, host=None,
                disk_move_type="moveAllDiskBackingsAndAllowSharing",
                devices=None, spec=None):
    client_factory = session.vim.client.factory
    rel_spec = spec or relocate_vm_spec(client_factory, res_pool, datastore,
                                        host, disk_move_type, devices)
    relocate_task = session._call_method(session.vim, "RelocateVM_Task",
                                         vm_ref, spec=rel_spec)
    session._wait_for_task(relocate_task)


def get_machine_id_change_spec(client_factory, machine_id_str):
    """Builds the machine id change config spec."""
    virtual_machine_config_spec = client_factory.create(
                                  'ns0:VirtualMachineConfigSpec')

    opt = client_factory.create('ns0:OptionValue')
    opt.key = "machine.id"
    opt.value = machine_id_str
    virtual_machine_config_spec.extraConfig = [opt]
    return virtual_machine_config_spec


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
    opt_keymap = client_factory.create('ns0:OptionValue')
    opt_keymap.key = "RemoteDisplay.vnc.keyMap"
    opt_keymap.value = CONF.vmware.vnc_keymap

    extras = [opt_enabled, opt_port, opt_keymap]

    virtual_machine_config_spec.extraConfig = extras
    return virtual_machine_config_spec


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
    with vutil.WithRetrieval(session.vim, result) as objects:
        for obj in objects:
            if not hasattr(obj, 'propSet') or not obj.propSet:
                continue
            dynamic_prop = obj.propSet[0]
            option_value = dynamic_prop.val
            vnc_port = option_value.value
            vnc_ports.add(int(vnc_port))
    return vnc_ports


def _get_object_for_value(objects, value):
    for object in objects:
        if object.propSet[0].val == value:
            return object.obj


def _get_object_for_optionvalue(objects, value):
    for object in objects:
        if hasattr(object, "propSet") and object.propSet:
            if object.propSet[0].val.value == value:
                return object.obj


def _get_object_from_results(session, results, value, func):
    with vutil.WithRetrieval(session.vim, results) as objects:
        return func(objects, value)


def get_vm_ref_from_name(session, vm_name, base_obj=None, path=None):
    """Get reference to the VM with the name specified.

    This method reads all of the names of the VM's that are running
    on the backend, then it filters locally the matching vm_name.
    It is far more optimal to use _get_vm_ref_from_vm_uuid.
    """
    property_list = ["name"]
    if not base_obj:  # Legacy: It doesn't scale
        vms = session._call_method(
            vim_util, "get_objects",
            "VirtualMachine", property_list)
    else:
        if not path:
            raise ValueError("Method needs base_obj and path")
        vms = session._call_method(
            vim_util, "get_inner_objects", base_obj, path,
            "VirtualMachine", property_list)

    return _get_object_from_results(session, vms, vm_name,
                                    _get_object_for_value)


def _get_vm_ref_from_vm_uuid(session, instance_uuid):
    """Get reference to the VM.

    The method will make use of FindAllByUuid to get the VM reference.
    This method finds all VM's on the backend that match the
    instance_uuid, more specifically all VM's on the backend that have
    'config_spec.instanceUuid' set to 'instance_uuid'.
    """
    vm_refs = session._call_method(
        session.vim,
        "FindAllByUuid",
        session.vim.service_content.searchIndex,
        uuid=instance_uuid,
        vmSearch=True,
        instanceUuid=True)
    if vm_refs:
        return vm_refs[0]


def find_by_inventory_path(session, inv_path):
    return session._call_method(
        session.vim,
        "FindByInventoryPath",
        session.vim.service_content.searchIndex,
        inventoryPath=inv_path)


def _get_vm_ref_from_extraconfig(session, instance_uuid):
    """Get reference to the VM with the uuid specified."""
    vms = session._call_method(vim_util, "get_objects",
                "VirtualMachine", ['config.extraConfig["nvp.vm-uuid"]'])
    return _get_object_from_results(session, vms, instance_uuid,
                                     _get_object_for_optionvalue)


class VmMoRefProxy(StableMoRefProxy):
    def __init__(self, ref, uuid):
        super(VmMoRefProxy, self).__init__(ref)
        self._uuid = uuid

    def fetch_moref(self, session):
        vm_value_cache_delete(self._uuid)
        self.moref = search_vm_ref_by_identifier(session, self._uuid)
        if not self.moref:
            raise exception.InstanceNotFound(instance_id=self._uuid)
        vm_ref_cache_update(self._uuid, self.moref)


def get_vm_ref(session, instance):
    """Get reference to the VM through uuid."""
    moref = vm_ref_cache_get(instance.uuid)
    stable_ref = VmMoRefProxy(moref, instance.uuid)
    if not moref:
        stable_ref.fetch_moref(session)
    return stable_ref


def search_vm_ref_by_identifier(session, identifier):
    """Searches VM reference using the identifier.

    This method is primarily meant to separate out part of the logic for
    vm_ref search that could be use directly in the special case of
    migrating the instance. For querying VM linked to an instance always
    use get_vm_ref instead.
    """
    vm_ref = (_get_vm_ref_from_vm_uuid(session, identifier) or
              _get_vm_ref_from_extraconfig(session, identifier))
    return vm_ref


def get_host_ref_for_vm(session, instance):
    """Get a MoRef to the ESXi host currently running an instance."""

    vm_ref = get_vm_ref(session, instance)
    return session._call_method(vutil, "get_object_property",
                                vm_ref, "runtime.host")


def get_host_name_for_vm(session, instance):
    """Get the hostname of the ESXi host currently running an instance."""

    host_ref = get_host_ref_for_vm(session, instance)
    return session._call_method(vutil, "get_object_property",
                                host_ref, "name")


def get_vm_state(session, instance):
    vm_ref = get_vm_ref(session, instance)
    vm_state = session._call_method(vutil, "get_object_property",
                                    vm_ref, "runtime.powerState")
    return constants.POWER_STATES[vm_state]


def get_vm_name(session, vm_ref):
    return vim_util.get_object_property(session, vm_ref, "name")


def _set_host_reservations(stats, host_reservations_map, host_moref):
    """Compute the number of vcpus and memory in MB reserved for the host from
    the configured reservations or the default.

    For every host, both vcpus and memory can be given as static number or in
    percent, with static number taking priority.
    """
    host_vcpus = stats["vcpus"]
    host_memory_mb = stats["memory_mb"]
    stats["vcpus_reserved"] = 0
    stats["memory_mb_reserved"] = 0

    default_key = _HOST_RESERVATIONS_DEFAULT_KEY
    host_reservations = host_reservations_map.get(default_key, {})
    group_reservations = host_reservations_map.get(host_moref.value, {})
    for key in ['vcpus', 'vcpus_percent', 'memory_mb', 'memory_percent']:
        if key in group_reservations:
            host_reservations[key] = group_reservations[key]

    if not host_reservations:
        return

    # compute the number of vcpus
    if host_reservations.get('vcpus') is not None:
        vcpus = max(0, host_reservations['vcpus'])
        stats['vcpus_reserved'] = min(host_vcpus, vcpus)
    elif host_reservations.get('vcpus_percent') is not None:
        percent = max(0, min(100, host_reservations['vcpus_percent']))
        # This will round down.
        stats['vcpus_reserved'] = host_vcpus * percent // 100

    # compute the memory in MB
    if host_reservations.get('memory_mb') is not None:
        memory_mb = max(0, host_reservations['memory_mb'])
        stats['memory_mb_reserved'] = min(host_memory_mb, memory_mb)
    elif host_reservations.get('memory_percent') is not None:
        percent = max(0, min(100, host_reservations['memory_percent']))
        # This will round down.
        stats['memory_mb_reserved'] = host_memory_mb * percent // 100


def _get_host_reservations_map(groups=None):
    """return a mapping from hosts to reservations

    Reservations are read from CONF.vmware.hostgroup_reservations_json_file,
    which is mapping from hostgroup to reservation. We thus look up the
    hostgroups we find in the mapping and create a mapping from each host in
    that hostgroup to the reservation.
    """
    if groups is None:
        groups = []

    if not CONF.vmware.hostgroup_reservations_json_file:
        return {}

    with open(CONF.vmware.hostgroup_reservations_json_file, 'rb') as f:
        reservations = jsonutils.load(f)

    hrm = {}

    default = reservations.get(_HOST_RESERVATIONS_DEFAULT_KEY)
    if default is not None:
        hrm[_HOST_RESERVATIONS_DEFAULT_KEY] = default

    for group in groups:
        if not hasattr(group, 'host'):
            continue

        if group.name not in reservations:
            continue

        for host_moref in group.host:
            reservation = reservations[group.name]
            hrm[host_moref.value] = reservation
    return hrm


# Only for satisfying the tests, and to ensure it is producing the same results
def get_stats_from_cluster(session, cluster):
    return aggregate_stats_from_cluster(
        get_stats_from_cluster_per_host(session, cluster))


def aggregate_stats_from_cluster(host_stats):
    """Get the aggregate resource stats of a cluster."""
    total_vcpus = 0
    total_vcpus_used = 0
    total_vcpus_reserved = 0
    max_vcpus_per_host = 0

    total_memory_mb = 0
    total_memory_mb_used = 0
    total_memory_mb_reserved = 0
    max_mem_mb_per_host = 0

    # NOTE (jakobk): For the total amount of hosts it doesn't matter
    # whether the host is in MM or unreachable, because the count is
    # used to calculate safety margins for resource allocations, and MM
    # or otherwise unreachable hosts is precisely what that is supposed
    # to guard against.
    total_hypervisor_count = len(host_stats)
    aggregated_cpu_info = {}
    hosts_mhz = []

    for stats in host_stats.values():
        if not stats["available"]:
            continue
        # Total vcpus is the sum of all pCPUs of individual hosts
        # The overcommitment ratio is factored in by the scheduler
        vcpus = stats["vcpus"]
        total_vcpus += vcpus
        vcpus_used = stats["vcpus_used"]
        total_vcpus_used += vcpus_used
        vcpus_reserved = stats["vcpus_reserved"]
        total_vcpus_reserved += vcpus_reserved
        max_vcpus_per_host = max(max_vcpus_per_host,
                                 vcpus - vcpus_reserved)

        memory_mb = stats["memory_mb"]
        total_memory_mb += memory_mb
        memory_mb_used = stats["memory_mb_used"]
        total_memory_mb_used += memory_mb_used
        memory_mb_reserved = stats["memory_mb_reserved"]
        total_memory_mb_reserved += memory_mb_reserved
        max_mem_mb_per_host = max(max_mem_mb_per_host,
                                  memory_mb - memory_mb_reserved)
        if not aggregated_cpu_info:
            aggregated_cpu_info = stats["cpu_info"].copy()
        else:
            cpu_info = stats["cpu_info"]
            for key, value in cpu_info.items():
                if aggregated_cpu_info.get(key) != value:
                    aggregated_cpu_info[key] = "Mismatching values"
        host_mhz = stats["cpu_mhz"]
        if host_mhz:
            hosts_mhz.append(host_mhz)
    hosts_mhz.sort()
    # NOTE(jakobk): The proper median for an even number of values is the
    # average of the two middle values, but we don't need that precision.
    median_cpu_mhz = hosts_mhz[len(hosts_mhz) // 2] if hosts_mhz else 0

    # Calculate VM-reservable memory as a ratio of total available
    # memory, depending on either the configured tolerance for failed
    # hypervisors or a single configurable ratio.
    max_fail_hvs = \
        CONF.vmware.memory_reservation_cluster_hosts_max_fail
    if max_fail_hvs and total_hypervisor_count:
        vm_reservable_memory_ratio = \
            (1 - max_fail_hvs / total_hypervisor_count)
    else:
        vm_reservable_memory_ratio = \
            CONF.vmware.memory_reservation_max_ratio_fallback

    return {
        "vcpus": total_vcpus,
        "vcpus_used": total_vcpus_used,
        "vcpus_reserved": total_vcpus_reserved,
        "max_vcpus_per_host": max_vcpus_per_host,
        "memory_mb": total_memory_mb,
        "memory_mb_used": total_memory_mb_used,
        "memory_mb_reserved": total_memory_mb_reserved,
        "max_mem_mb_per_host": max_mem_mb_per_host,
        "vm_reservable_memory_ratio": vm_reservable_memory_ratio,
        "cpu_info": aggregated_cpu_info,
        "cpu_mhz": median_cpu_mhz,
    }


def _host_props_to_cpu_info(host_props):
    processor_type = None
    cpu_vendor = None
    hardware_cpu_pkg = host_props.get("hardware.cpuPkg")
    if hardware_cpu_pkg and hardware_cpu_pkg.HostCpuPackage:
        t = hardware_cpu_pkg.HostCpuPackage[0]
        processor_type = t.description
        cpu_vendor = t.vendor.title()

    features = []
    if "config.featureCapability" in host_props:
        feature_capability = host_props["config.featureCapability"]
        for feature in feature_capability.HostFeatureCapability:
            if not feature.featureName.startswith("cpuid."):
                continue
            if feature.value != "1":
                continue

            name = feature.featureName
            features.append(name.split(".", 1)[1].lower())
    cpu_info = {
        "model": processor_type,
        "vendor": cpu_vendor,
        "features": sorted(features)
    }
    hardware_cpu_info = host_props.get("hardware.cpuInfo")
    if hardware_cpu_info:
        cpu_info["topology"] = {
            "cores": hardware_cpu_info.numCpuCores,
            "sockets": hardware_cpu_info.numCpuPackages,
            "threads": hardware_cpu_info.numCpuThreads
        }
    return cpu_info


def _set_hypervisor_type_and_version(stats, host_props):
    product = host_props.get("summary.config.product")
    if not product:
        return

    stats["hypervisor_type"] = product.name
    stats["hypervisor_version"] = convert_version_to_int(product.version)


def _process_host_stats(obj, host_reservations_map):
    host_props = propset_dict(obj.propSet)
    runtime_summary = host_props["summary.runtime"]
    hardware_summary = host_props.get("summary.hardware")
    stats_summary = host_props.get("summary.quickStats")
    # Total vcpus is the sum of all pCPUs of individual hosts
    # The overcommitment ratio is factored in by the scheduler
    threads = getattr(hardware_summary, "numCpuThreads", 0)
    mem_mb = getattr(hardware_summary, "memorySize", 0) // units.Mi

    stats = {
        "available": (not runtime_summary.inMaintenanceMode and
                      runtime_summary.connectionState == "connected"),
        "vcpus": threads,
        "vcpus_used": 0,
        "memory_mb": mem_mb,
        "memory_mb_used": getattr(stats_summary, "overallMemoryUsage", 0),
        "cpu_info": _host_props_to_cpu_info(host_props),
        "cpu_mhz": getattr(hardware_summary, "cpuMhz"),
    }

    _set_hypervisor_type_and_version(stats, host_props)
    _set_host_reservations(stats, host_reservations_map, obj.obj)
    return host_props["name"], stats


def get_stats_from_cluster_per_host(session, cluster):
    """Get the resource stats per host of a cluster."""
    host_mors, host_reservations_map = \
        get_hosts_and_reservations_for_cluster(session, cluster)

    if not host_mors:
        return {}

    result = session._call_method(vim_util,
                    "get_properties_for_a_collection_of_objects",
                    "HostSystem", host_mors,
                    ["name", "summary.hardware", "summary.runtime",
                     "summary.quickStats", "summary.config.product",
                     "hardware.cpuPkg", "hardware.cpuInfo",
                     "config.featureCapability",
                    ])
    with vutil.WithRetrieval(session.vim, result) as objects:
        return dict(_process_host_stats(obj, host_reservations_map)
                    for obj in objects if hasattr(obj, "propSet"))


def get_hosts_and_reservations_for_cluster(session, cluster):
    # Get the Host and Resource Pool Managed Object Refs
    admission_policy_key = "configuration.dasConfig.admissionControlPolicy"
    props = ["host", "resourcePool", admission_policy_key]
    if CONF.vmware.hostgroup_reservations_json_file:
        props.append("configurationEx")
    prop_dict = session._call_method(vutil,
                                     "get_object_properties_dict",
                                     cluster,
                                     props)
    if not prop_dict:
        return None, None

    failover_hosts = []
    policy = prop_dict.get(admission_policy_key)
    if policy and hasattr(policy, 'failoverHosts'):
        failover_hosts = set(h.value for h in policy.failoverHosts)

    group_ret = getattr(prop_dict.get('configurationEx'), 'group', None)

    host_ret = prop_dict.get('host')

    if not host_ret:
        return None, None

    host_mors = [m for m in host_ret.ManagedObjectReference
                            if m.value not in failover_hosts]
    return host_mors, _get_host_reservations_map(group_ret)


def get_host_ref(session, cluster=None):
    """Get reference to a host within the cluster specified."""
    if cluster is None:
        results = session._call_method(vim_util, "get_objects",
                                       "HostSystem")
        session._call_method(vutil, 'cancel_retrieval',
                             results)
        host_mor = results.objects[0].obj
    else:
        host_ret = session._call_method(vutil, "get_object_property",
                                        cluster, "host")
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
    | http://pubs.vmware.com/vsphere-51/index.jsp
    |    #com.vmware.wssdk.apiref.doc/
    |        vmodl.query.PropertyCollector.ObjectContent.html

    :param propset: a property "set" from ObjectContent
    :return: dictionary representing property set
    """
    if propset is None:
        return {}

    return {prop.name: prop.val for prop in propset}


def get_vmdk_backed_disk_device(hardware_devices, uuid):
    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                "VirtualDiskFlatVer2BackingInfo" and
                getattr(device.backing, 'uuid', None) == uuid):
            return device


def get_vmdk_volume_disk(hardware_devices, path=None):
    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk"):
            if not path or path == device.backing.fileName:
                return device


def get_res_pool_ref(session, cluster):
    """Get the resource pool."""
    # Get the root resource pool of the cluster
    res_pool_ref = session._call_method(vutil,
                                        "get_object_property",
                                        cluster,
                                        "resourcePool")
    return res_pool_ref


def get_all_cluster_mors(session):
    """Get all the clusters in the vCenter."""
    try:
        results = session._call_method(vim_util, "get_objects",
                                        "ClusterComputeResource", ["name"])
        with vutil.WithRetrieval(session.vim, results) as objects:
            return list(objects)
    except Exception as excep:
        LOG.warning("Failed to get cluster references %s", excep)


def get_cluster_ref_by_name(session, cluster_name):
    """Get reference to the vCenter cluster with the specified name."""
    all_clusters = get_all_cluster_mors(session)
    for cluster in all_clusters:
        if (hasattr(cluster, 'propSet') and cluster.propSet and
                    cluster.propSet[0].val == cluster_name):
            return cluster.obj


def get_datastore_ref_by_name(session, datastore_name):
    """Return the ManagedObjectReference to the datastore with the given name

    Returns None if no datastore with that name can be found.
    """
    try:
        results = session._call_method(vim_util, "get_objects",
                                       "Datastore", ["name"])
        with vutil.WithRetrieval(session.vim, results) as objects:
            for datastore in objects:
                if not getattr(datastore, 'propSet', None):
                    continue

                if datastore.propSet[0].val != datastore_name:
                    continue

                return datastore.obj
    except Exception as exc:
        LOG.warning("Failed to get datastore references %s", exc)


def get_vmdk_adapter_type(adapter_type):
    """Return the adapter type to be used in vmdk descriptor.

    Adapter type in vmdk descriptor is same for LSI-SAS, LSILogic & ParaVirtual
    because Virtual Disk Manager API does not recognize the newer controller
    types.
    """
    if adapter_type in [constants.ADAPTER_TYPE_LSILOGICSAS,
                        constants.ADAPTER_TYPE_PARAVIRTUAL]:
        vmdk_adapter_type = constants.DEFAULT_ADAPTER_TYPE
    else:
        vmdk_adapter_type = adapter_type
    return vmdk_adapter_type


@loopingcall.RetryDecorator(
    max_retry_count=20, inc_sleep_time=2, max_sleep_time=20,
    exceptions=(vexc.VimFaultException,))
def create_vm(session, instance, vm_folder, config_spec, res_pool_ref):
    """Create VM on ESX host."""
    LOG.debug("Creating VM on the ESX host", instance=instance)
    vm_create_task = session._call_method(
        session.vim,
        "CreateVM_Task", vm_folder,
        config=config_spec, pool=res_pool_ref)
    try:
        task_info = session._wait_for_task(vm_create_task)
    except vexc.VMwareDriverException:
        # An invalid guestId will result in an error with no specific fault
        # type and the generic error 'A specified parameter was not correct'.
        # As guestId is user-editable, we try to help the user out with some
        # additional information if we notice that guestId isn't in our list of
        # known-good values.
        # We don't check this in advance or do anything more than warn because
        # we can't guarantee that our list of known-good guestIds is complete.
        # Consequently, a value which we don't recognise may in fact be valid.
        with excutils.save_and_reraise_exception():
            if config_spec.guestId not in constants.VALID_OS_TYPES:
                LOG.warning('vmware_ostype from image is not recognised: '
                            '\'%(ostype)s\'. An invalid os type may be '
                            'one cause of this instance creation failure',
                            {'ostype': config_spec.guestId})
    LOG.debug("Created VM on the ESX host", instance=instance)
    return task_info.result


def _destroy_vm(session, instance, vm_ref=None):
    if not vm_ref:
        vm_ref = get_vm_ref(session, instance)
    LOG.debug("Destroying the VM", instance=instance)
    destroy_task = session._call_method(session.vim, "Destroy_Task",
                                        vm_ref)
    session._wait_for_task(destroy_task)
    LOG.info("Destroyed the VM", instance=instance)


def destroy_vm(session, instance, vm_ref=None):
    """Destroy a VM instance. Assumes VM is powered off."""
    try:
        return _destroy_vm(session, instance, vm_ref=vm_ref)
    except vexc.VimFaultException as e:
        with excutils.save_and_reraise_exception() as ctx:
            LOG.exception('Destroy VM failed', instance=instance)
            # we need the `InvalidArgument` fault to bubble out of this
            # function so it can be acted upon on higher levels
            if 'InvalidArgument' not in e.fault_list:
                ctx.reraise = False
    except Exception:
        LOG.exception('Destroy VM failed', instance=instance)


def mark_vm_as_template(session, instance, vm_ref=None):
    """Mark a VM instance as template. Assumes VM is powered off."""
    try:
        if not vm_ref:
            vm_ref = get_vm_ref(session, instance)
        LOG.debug("Marking the VM as template", instance=instance)
        session._call_method(session.vim, "MarkAsTemplate", vm_ref)
        LOG.info("Marked the VM as template", instance=instance)
    except Exception:
        LOG.exception('Mark VM as template failed', instance=instance)


def create_virtual_disk(session, dc_ref, adapter_type, disk_type,
                        virtual_disk_path, size_in_kb):
    # Create a Virtual Disk of the size of the flat vmdk file. This is
    # done just to generate the meta-data file whose specifics
    # depend on the size of the disk, thin/thick provisioning and the
    # storage adapter type.
    LOG.debug("Creating Virtual Disk of size  "
              "%(vmdk_file_size_in_kb)s KB and adapter type "
              "%(adapter_type)s on the data store",
              {"vmdk_file_size_in_kb": size_in_kb,
               "adapter_type": adapter_type})

    vmdk_create_spec = get_vmdk_create_spec(
            session.vim.client.factory,
            size_in_kb,
            adapter_type,
            disk_type)

    vmdk_create_task = session._call_method(
            session.vim,
            "CreateVirtualDisk_Task",
            session.vim.service_content.virtualDiskManager,
            name=virtual_disk_path,
            datacenter=dc_ref,
            spec=vmdk_create_spec)

    session._wait_for_task(vmdk_create_task)
    LOG.debug("Created Virtual Disk of size %(vmdk_file_size_in_kb)s"
              " KB and type %(disk_type)s",
              {"vmdk_file_size_in_kb": size_in_kb,
               "disk_type": disk_type})


def copy_virtual_disk(session, dc_ref, source, dest):
    """Copy a sparse virtual disk to a thin virtual disk.

    This is also done to generate the meta-data file whose specifics
    depend on the size of the disk, thin/thick provisioning and the
    storage adapter type.

    :param session: - session for connection
    :param dc_ref: - data center reference object
    :param source: - source datastore path
    :param dest: - destination datastore path
    :returns: None
    """
    LOG.debug("Copying Virtual Disk %(source)s to %(dest)s",
              {'source': source, 'dest': dest})
    vim = session.vim
    vmdk_copy_task = session._call_method(
            vim,
            "CopyVirtualDisk_Task",
            vim.service_content.virtualDiskManager,
            sourceName=source,
            sourceDatacenter=dc_ref,
            destName=dest)
    session._wait_for_task(vmdk_copy_task)
    LOG.debug("Copied Virtual Disk %(source)s to %(dest)s",
              {'source': source, 'dest': dest})


def reconfigure_vm(session, vm_ref, config_spec):
    """Reconfigure a VM according to the config spec."""
    reconfig_task = session._call_method(session.vim,
                                         "ReconfigVM_Task", vm_ref,
                                         spec=config_spec)
    session._wait_for_task(reconfig_task)


def power_on_instance(session, instance, vm_ref=None):
    """Power on the specified instance."""

    if vm_ref is None:
        vm_ref = get_vm_ref(session, instance)

    LOG.debug("Powering on the VM", instance=instance)
    try:
        poweron_task = session._call_method(
                                    session.vim,
                                    "PowerOnVM_Task", vm_ref)
        session._wait_for_task(poweron_task)
        LOG.debug("Powered on the VM", instance=instance)
    except vexc.InvalidPowerStateException:
        LOG.debug("VM already powered on", instance=instance)


def _get_vm_port_indices(session, vm_ref):
    extra_config = session._call_method(vutil,
                                        'get_object_property',
                                        vm_ref,
                                        'config.extraConfig')
    ports = []
    if extra_config is not None:
        options = extra_config.OptionValue
        for option in options:
            if (option.key.startswith('nvp.iface-id.') and
                    option.value != 'free'):
                ports.append(int(option.key.split('.')[2]))
    return ports


def get_attach_port_index(session, vm_ref):
    """Get the first free port index."""
    ports = _get_vm_port_indices(session, vm_ref)
    # No ports are configured on the VM
    if not ports:
        return 0
    ports.sort()
    configured_ports_len = len(ports)
    # Find the first free port index
    for port_index in range(configured_ports_len):
        if port_index != ports[port_index]:
            return port_index
    return configured_ports_len


def get_vm_detach_port_index(session, vm_ref, iface_id):
    extra_config = session._call_method(vutil,
                                        'get_object_property',
                                        vm_ref,
                                        'config.extraConfig')
    if extra_config is not None:
        options = extra_config.OptionValue
        for option in options:
            if (option.key.startswith('nvp.iface-id.') and
                option.value == iface_id):
                return int(option.key.split('.')[2])


def power_off_instance(session, instance, vm_ref=None):
    """Power off the specified instance.

    Returns True if the VM was powered off by this call, or False
    of the VM was already powered off.
    """

    if vm_ref is None:
        vm_ref = get_vm_ref(session, instance)

    LOG.debug("Powering off the VM", instance=instance)
    try:
        poweroff_task = session._call_method(session.vim,
                                         "PowerOffVM_Task", vm_ref)
        session._wait_for_task(poweroff_task)
        LOG.debug("Powered off the VM", instance=instance)
        return True
    except vexc.InvalidPowerStateException:
        LOG.debug("VM already powered off", instance=instance)
        return False


def find_rescue_device(hardware_devices, instance):
    """Returns the rescue device.

    The method will raise an exception if the rescue device does not
    exist. The resuce device has suffix '-rescue.vmdk'.
    :param hardware_devices: the hardware devices for the instance
    :param instance: nova.objects.instance.Instance object
    :return: the rescue disk device object
    """
    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                'VirtualDiskFlatVer2BackingInfo' and
                device.backing.fileName.endswith('-rescue.vmdk')):
            return device

    msg = _('Rescue device does not exist for instance %s') % instance.uuid
    raise exception.NotFound(msg)


def get_ephemeral_name(id_):
    return 'ephemeral_%d.vmdk' % id_


def _detach_and_delete_devices_config_spec(client_factory, devices):
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    device_config_spec = []
    for device in devices:
        virtual_device_config = client_factory.create(
                                'ns0:VirtualDeviceConfigSpec')
        virtual_device_config.operation = "remove"
        virtual_device_config.device = device
        virtual_device_config.fileOperation = "destroy"
        device_config_spec.append(virtual_device_config)
    config_spec.deviceChange = device_config_spec
    return config_spec


def detach_devices_from_vm(session, vm_ref, devices):
    """Detach specified devices from VM."""
    client_factory = session.vim.client.factory
    config_spec = _detach_and_delete_devices_config_spec(
        client_factory, devices)
    reconfigure_vm(session, vm_ref, config_spec)


def get_ephemerals(session, vm_ref):
    devices = []
    hardware_devices = get_hardware_devices(session, vm_ref)

    for device in hardware_devices:
        if device.__class__.__name__ == "VirtualDisk":
            if (device.backing.__class__.__name__ ==
                    "VirtualDiskFlatVer2BackingInfo"):
                if 'ephemeral' in device.backing.fileName:
                    devices.append(device)
    return devices


def get_swap(session, vm_ref):
    hardware_devices = get_hardware_devices(session, vm_ref)

    for device in hardware_devices:
        if (device.__class__.__name__ == "VirtualDisk" and
                device.backing.__class__.__name__ ==
                    "VirtualDiskFlatVer2BackingInfo" and
                'swap' in device.backing.fileName):
            return device


def create_folder(session, parent_folder_ref, name):
    """Creates a folder in vCenter

    A folder of 'name' will be created under the parent folder.
    The moref of the folder is returned.
    """

    LOG.debug("Creating folder: %(name)s. Parent ref: %(parent)s.",
              {'name': name,
               'parent': vutil.get_moref_value(parent_folder_ref)})
    try:
        folder = session._call_method(session.vim, "CreateFolder",
                                      parent_folder_ref, name=name)
        LOG.info("Created folder: %(name)s in parent %(parent)s.",
                 {'name': name,
                  'parent': vutil.get_moref_value(parent_folder_ref)})
    except vexc.DuplicateName as e:
        LOG.debug("Folder already exists: %(name)s. Parent ref: %(parent)s.",
                  {'name': name,
                   'parent': vutil.get_moref_value(parent_folder_ref)})
        val = e.details['object']
        folder = vutil.get_moref(val, 'Folder')
    return folder


def folder_ref_cache_update(path, folder_ref):
    _FOLDER_PATH_REF_MAPPING[path] = folder_ref


def folder_ref_cache_get(path):
    return _FOLDER_PATH_REF_MAPPING.get(path)


def _get_vm_name(display_name, id_):
    if display_name:
        return '%s (%s)' % (display_name[:41], id_[:36])

    return id_[:36]


def rename_vm(session, vm_ref, instance, vm_name=None):
    vm_name = vm_name or _get_vm_name(instance.display_name, instance.uuid)
    rename_task = session._call_method(session.vim, "Rename_Task", vm_ref,
                                       newName=vm_name)
    session._wait_for_task(rename_task)


def create_service_locator_name_password(client_factory, username, password):
    """Creates a ServiceLocatorNamePassword object, which in turn is
    derived of ServiceLocatorCredential
    """
    o = client_factory.create('ns0:ServiceLocatorNamePassword')
    o.username = username
    o.password = password
    return o


def get_sha1_ssl_thumbprint(url, timeout=1):
    """Returns the sha-1 thumbprint of the ssl cert of the vcenter or None
    """
    try:
        parsed_url = six.moves.urllib.parse.urlparse(url)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        wrappedSocket = ssl.wrap_socket(sock)
        thumb = None
        wrappedSocket.connect((parsed_url.hostname, parsed_url.port or 443))

        der_cert_bin = wrappedSocket.getpeercert(True)

        thumb = hashlib.sha1(der_cert_bin).hexdigest().upper()
        t = iter(thumb)
        return ':'.join(a + b for a, b in zip(t, t))
    except (OSError, ValueError, socket.timeout):
        return


def create_service_locator(client_factory, url, vcenter_instance_uuid,
        credential, ssl_thumbprint=None):
    """Creates a ServiceLocator WSDL-object

    :param client_factory: - factory for creating the object
    :param url: - url to the vcenter api
    :param vcenter_instance_uuid: - uuid of the vcenter instance
    :param credential: - An instance of ServiceLocatorCredential
        (See: create_service_locator_name_password)
    :param ssl_thumbprint: - The sha1 thumbprint of the cert of the instance
        (See: get_sha1_ssl_thumbprint)
    :returns: A ServiceLocator WSDL-object
    """

    # While it is nominally optional, operations seems to fail without it
    # We will do a best effort
    if not ssl_thumbprint:
        ssl_thumbprint = get_sha1_ssl_thumbprint(url)

    sl = client_factory.create('ns0:ServiceLocator')
    sl.url = url
    sl.instanceUuid = vcenter_instance_uuid
    sl.credential = credential
    sl.sslThumbprint = ssl_thumbprint
    return sl


def reconfigure_vm_device_change(session, vm_ref, device_change):
    """Reconfigure a VM to add/edit/remove devices.

    The device_change should be a VirtualDeviceConfigSpec.
    """
    if not device_change:
        return
    client_factory = session.vim.client.factory
    config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
    config_spec.deviceChange = device_change
    reconfigure_vm(session, vm_ref, config_spec)


def get_vmx_path(session, vm_ref):
    """Return DatastorePath object of the vmx file of the VM"""
    vmx_path = session._call_method(vutil, 'get_object_property',
                                    vm_ref, 'config.files.vmPathName')
    return ds_obj.DatastorePath.parse(vmx_path)


def _create_fcd_id_obj(client_factory, fcd_id):
    id_obj = client_factory.create('ns0:ID')
    id_obj.id = fcd_id
    return id_obj


def attach_fcd(
        session, vm_ref, fcd_id, ds_ref_val, controller_key, unit_number
    ):
    client_factory = session.vim.client.factory
    disk_id = _create_fcd_id_obj(client_factory, fcd_id)
    ds_ref = vutil.get_moref(ds_ref_val, 'Datastore')
    LOG.debug("Attaching fcd (id: %(fcd_id)s, datastore: %(ds_ref_val)s) to "
              "vm: %(vm_ref)s.",
              {'fcd_id': fcd_id,
               'ds_ref_val': ds_ref_val,
               'vm_ref': vutil.get_moref_value(vm_ref)})
    task = session._call_method(
        session.vim, "AttachDisk_Task", vm_ref, diskId=disk_id,
        datastore=ds_ref, controllerKey=controller_key, unitNumber=unit_number)
    session._wait_for_task(task)


def detach_fcd(session, vm_ref, fcd_id):
    client_factory = session.vim.client.factory
    disk_id = _create_fcd_id_obj(client_factory, fcd_id)
    LOG.debug("Detaching fcd (id: %(fcd_id)s) from vm: %(vm_ref)s.",
              {'fcd_id': fcd_id, 'vm_ref': vutil.get_moref_value(vm_ref)})
    task = session._call_method(
        session.vim, "DetachDisk_Task", vm_ref, diskId=disk_id)
    session._wait_for_task(task)
