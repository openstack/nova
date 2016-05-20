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
A fake VMware VI API implementation.
"""

import collections
import sys

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units
from oslo_utils import uuidutils
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
import six

from nova import exception
from nova.virt.vmwareapi import constants

_CLASSES = ['Datacenter', 'Datastore', 'ResourcePool', 'VirtualMachine',
            'Network', 'HostSystem', 'HostNetworkSystem', 'Task', 'session',
            'files', 'ClusterComputeResource', 'HostStorageSystem',
            'Folder']

_FAKE_FILE_SIZE = 1024
_FAKE_VCENTER_UUID = '497c514c-ef5e-4e7f-8d93-ec921993b93a'

_db_content = {}
_array_types = {}
_vim_map = {}

LOG = logging.getLogger(__name__)


def reset():
    """Resets the db contents."""
    cleanup()
    create_network()
    create_folder()
    create_host_network_system()
    create_host_storage_system()
    ds_ref1 = create_datastore('ds1', 1024, 500)
    create_host(ds_ref=ds_ref1)
    ds_ref2 = create_datastore('ds2', 1024, 500)
    create_host(ds_ref=ds_ref2)
    create_datacenter('dc1', ds_ref1)
    create_datacenter('dc2', ds_ref2)
    create_res_pool()
    create_cluster('test_cluster', ds_ref1)
    create_cluster('test_cluster2', ds_ref2)


def cleanup():
    """Clear the db contents."""
    for c in _CLASSES:
        # We fake the datastore by keeping the file references as a list of
        # names in the db
        if c == 'files':
            _db_content[c] = []
        else:
            _db_content[c] = {}


def _create_object(table, table_obj):
    """Create an object in the db."""
    _db_content.setdefault(table, {})
    _db_content[table][table_obj.obj] = table_obj


def _get_object(obj_ref):
    """Get object for the give reference."""
    return _db_content[obj_ref.type][obj_ref]


def _get_objects(obj_type):
    """Get objects of the type."""
    lst_objs = FakeRetrieveResult()
    for key in _db_content[obj_type]:
        lst_objs.add_object(_db_content[obj_type][key])
    return lst_objs


def _convert_to_array_of_mor(mors):
    """Wraps the given array into a DataObject."""
    array_of_mors = DataObject()
    array_of_mors.ManagedObjectReference = mors
    return array_of_mors


def _convert_to_array_of_opt_val(optvals):
    """Wraps the given array into a DataObject."""
    array_of_optv = DataObject()
    array_of_optv.OptionValue = optvals
    return array_of_optv


def _create_array_of_type(t):
    """Returns an array to contain objects of type t."""
    if t in _array_types:
        return _array_types[t]()

    array_type_name = 'ArrayOf%s' % t
    array_type = type(array_type_name, (DataObject,), {})

    def __init__(self):
        super(array_type, self).__init__(array_type_name)
        setattr(self, t, [])

    setattr(array_type, '__init__', __init__)

    _array_types[t] = array_type
    return array_type()


class FakeRetrieveResult(object):
    """Object to retrieve a ObjectContent list."""

    def __init__(self, token=None):
        self.objects = []
        if token is not None:
            self.token = token

    def add_object(self, object):
        self.objects.append(object)


def _get_object_refs(obj_type):
    """Get object References of the type."""
    lst_objs = []
    for key in _db_content[obj_type]:
        lst_objs.append(key)
    return lst_objs


def _update_object(table, table_obj):
    """Update objects of the type."""
    _db_content[table][table_obj.obj] = table_obj


class Prop(object):
    """Property Object base class."""

    def __init__(self, name=None, val=None):
        self.name = name
        self.val = val


class ManagedObjectReference(object):
    """A managed object reference is a remote identifier."""

    def __init__(self, name="ManagedObject", value=None):
        super(ManagedObjectReference, self)
        # Managed Object Reference value attributes
        # typically have values like vm-123 or
        # host-232 and not UUID.
        self.value = value
        # Managed Object Reference type
        # attributes hold the name of the type
        # of the vCenter object the value
        # attribute is the identifier for
        self.type = name
        self._type = name


class ObjectContent(object):
    """ObjectContent array holds dynamic properties."""

    # This class is a *fake* of a class sent back to us by
    # SOAP. It has its own names. These names are decided
    # for us by the API we are *faking* here.
    def __init__(self, obj_ref, prop_list=None, missing_list=None):
        self.obj = obj_ref

        if not isinstance(prop_list, collections.Iterable):
            prop_list = []

        if not isinstance(missing_list, collections.Iterable):
            missing_list = []

        # propSet is the name your Python code will need to
        # use since this is the name that the API will use
        if prop_list:
            self.propSet = prop_list

        # missingSet is the name your python code will
        # need to use since this is the name that the
        # API we are talking to will use.
        if missing_list:
            self.missingSet = missing_list


class ManagedObject(object):
    """Managed Object base class."""
    _counter = 0

    def __init__(self, mo_id_prefix="obj"):
        """Sets the obj property which acts as a reference to the object."""
        object.__setattr__(self, 'mo_id', self._generate_moid(mo_id_prefix))
        object.__setattr__(self, 'propSet', [])
        object.__setattr__(self, 'obj',
                           ManagedObjectReference(self.__class__.__name__,
                                                  self.mo_id))

    def set(self, attr, val):
        """Sets an attribute value. Not using the __setattr__ directly for we
        want to set attributes of the type 'a.b.c' and using this function
        class we set the same.
        """
        self.__setattr__(attr, val)

    def get(self, attr):
        """Gets an attribute. Used as an intermediary to get nested
        property like 'a.b.c' value.
        """
        return self.__getattr__(attr)

    def delete(self, attr):
        """Deletes an attribute."""
        self.propSet = filter(lambda elem: elem.name != attr, self.propSet)

    def __setattr__(self, attr, val):
        # TODO(hartsocks): this is adds unnecessary complexity to the class
        for prop in self.propSet:
            if prop.name == attr:
                prop.val = val
                return
        elem = Prop()
        elem.name = attr
        elem.val = val
        self.propSet.append(elem)

    def __getattr__(self, attr):
        # TODO(hartsocks): remove this
        # in a real ManagedObject you have to iterate the propSet
        # in a real ManagedObject, the propSet is a *set* not a list
        for elem in self.propSet:
            if elem.name == attr:
                return elem.val
        msg = "Property %(attr)s not set for the managed object %(name)s"
        raise exception.NovaException(msg % {'attr': attr,
                                             'name': self.__class__.__name__})

    def _generate_moid(self, prefix):
        """Generates a new Managed Object ID."""
        self.__class__._counter += 1
        return prefix + "-" + str(self.__class__._counter)

    def __repr__(self):
        return jsonutils.dumps({elem.name: elem.val
                                for elem in self.propSet})


class DataObject(object):
    """Data object base class."""

    def __init__(self, obj_name=None):
        if obj_name is None:
            obj_name = 'ns0:' + self.__class__.__name__
        self.obj_name = obj_name

    def __repr__(self):
        return str(self.__dict__)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__


class HostInternetScsiHba(DataObject):
    """iSCSI Host Bus Adapter."""

    def __init__(self, iscsi_name=None):
        super(HostInternetScsiHba, self).__init__()
        self.device = 'vmhba33'
        self.key = 'key-vmhba33'
        self.iScsiName = iscsi_name


class FileAlreadyExists(DataObject):
    """File already exists class."""

    def __init__(self):
        super(FileAlreadyExists, self).__init__()
        self.__name__ = vexc.FILE_ALREADY_EXISTS


class FileNotFound(DataObject):
    """File not found class."""

    def __init__(self):
        super(FileNotFound, self).__init__()
        self.__name__ = vexc.FILE_NOT_FOUND


class FileFault(DataObject):
    """File fault."""

    def __init__(self):
        super(FileFault, self).__init__()
        self.__name__ = vexc.FILE_FAULT


class CannotDeleteFile(DataObject):
    """Cannot delete file."""

    def __init__(self):
        super(CannotDeleteFile, self).__init__()
        self.__name__ = vexc.CANNOT_DELETE_FILE


class FileLocked(DataObject):
    """File locked."""

    def __init__(self):
        super(FileLocked, self).__init__()
        self.__name__ = vexc.FILE_LOCKED


class VirtualDisk(DataObject):
    """Virtual Disk class."""

    def __init__(self, controllerKey=0, unitNumber=0):
        super(VirtualDisk, self).__init__()
        self.key = 0
        self.controllerKey = controllerKey
        self.unitNumber = unitNumber


class VirtualDiskFlatVer2BackingInfo(DataObject):
    """VirtualDiskFlatVer2BackingInfo class."""

    def __init__(self):
        super(VirtualDiskFlatVer2BackingInfo, self).__init__()
        self.thinProvisioned = False
        self.eagerlyScrub = False


class VirtualDiskRawDiskMappingVer1BackingInfo(DataObject):
    """VirtualDiskRawDiskMappingVer1BackingInfo class."""

    def __init__(self):
        super(VirtualDiskRawDiskMappingVer1BackingInfo, self).__init__()
        self.lunUuid = ""


class VirtualIDEController(DataObject):

    def __init__(self, key=0):
        self.key = key


class VirtualLsiLogicController(DataObject):
    """VirtualLsiLogicController class."""
    def __init__(self, key=0, scsiCtlrUnitNumber=0, busNumber=0):
        self.key = key
        self.busNumber = busNumber
        self.scsiCtlrUnitNumber = scsiCtlrUnitNumber
        self.device = []


class VirtualLsiLogicSASController(DataObject):
    """VirtualLsiLogicSASController class."""
    pass


class VirtualPCNet32(DataObject):
    """VirtualPCNet32 class."""

    def __init__(self):
        super(VirtualPCNet32, self).__init__()
        self.key = 4000


class OptionValue(DataObject):
    """OptionValue class."""

    def __init__(self, key=None, value=None):
        super(OptionValue, self).__init__()
        self.key = key
        self.value = value


class VirtualMachine(ManagedObject):
    """Virtual Machine class."""

    def __init__(self, **kwargs):
        super(VirtualMachine, self).__init__("vm")
        self.set("name", kwargs.get("name", 'test-vm'))
        self.set("runtime.connectionState",
                 kwargs.get("conn_state", "connected"))
        self.set("summary.config.guestId",
                 kwargs.get("guest", constants.DEFAULT_OS_TYPE))
        ds_do = kwargs.get("ds", None)
        self.set("datastore", _convert_to_array_of_mor(ds_do))
        self.set("summary.guest.toolsStatus", kwargs.get("toolsstatus",
                                "toolsOk"))
        self.set("summary.guest.toolsRunningStatus", kwargs.get(
                                "toolsrunningstate", "guestToolsRunning"))
        self.set("runtime.powerState", kwargs.get("powerstate", "poweredOn"))
        self.set("config.files.vmPathName", kwargs.get("vmPathName"))
        self.set("summary.config.numCpu", kwargs.get("numCpu", 1))
        self.set("summary.config.memorySizeMB", kwargs.get("mem", 1))
        self.set("summary.config.instanceUuid", kwargs.get("instanceUuid"))
        self.set("version", kwargs.get("version"))

        devices = _create_array_of_type('VirtualDevice')
        devices.VirtualDevice = kwargs.get("virtual_device", [])
        self.set("config.hardware.device", devices)

        exconfig_do = kwargs.get("extra_config", None)
        self.set("config.extraConfig",
                 _convert_to_array_of_opt_val(exconfig_do))
        if exconfig_do:
            for optval in exconfig_do:
                self.set('config.extraConfig["%s"]' % optval.key, optval)
        self.set('runtime.host', kwargs.get("runtime_host", None))
        self.device = kwargs.get("virtual_device", [])
        # Sample of diagnostics data is below.
        config = [
            ('template', False),
            ('vmPathName', 'fake_path'),
            ('memorySizeMB', 512),
            ('cpuReservation', 0),
            ('memoryReservation', 0),
            ('numCpu', 1),
            ('numEthernetCards', 1),
            ('numVirtualDisks', 1)]
        self.set("summary.config", config)

        quickStats = [
            ('overallCpuUsage', 0),
            ('overallCpuDemand', 0),
            ('guestMemoryUsage', 0),
            ('hostMemoryUsage', 141),
            ('balloonedMemory', 0),
            ('consumedOverheadMemory', 20)]
        self.set("summary.quickStats", quickStats)

        key1 = {'key': 'cpuid.AES'}
        key2 = {'key': 'cpuid.AVX'}
        runtime = [
            ('connectionState', 'connected'),
            ('powerState', 'poweredOn'),
            ('toolsInstallerMounted', False),
            ('suspendInterval', 0),
            ('memoryOverhead', 21417984),
            ('maxCpuUsage', 2000),
            ('featureRequirement', [key1, key2])]
        self.set("summary.runtime", runtime)

    def _update_extra_config(self, extra):
        extra_config = self.get("config.extraConfig")
        values = extra_config.OptionValue
        for value in values:
            if value.key == extra.key:
                value.value = extra.value
                return
        kv = DataObject()
        kv.key = extra.key
        kv.value = extra.value
        extra_config.OptionValue.append(kv)
        self.set("config.extraConfig", extra_config)
        extra_config = self.get("config.extraConfig")

    def reconfig(self, factory, val):
        """Called to reconfigure the VM. Actually customizes the property
        setting of the Virtual Machine object.
        """

        if hasattr(val, 'name') and val.name:
            self.set("name", val.name)

        if hasattr(val, 'extraConfig'):
            extraConfigs = _merge_extraconfig(
                                    self.get("config.extraConfig").OptionValue,
                                    val.extraConfig)
            self.get("config.extraConfig").OptionValue = extraConfigs

        if hasattr(val, 'instanceUuid') and val.instanceUuid is not None:
            if val.instanceUuid == "":
                val.instanceUuid = uuidutils.generate_uuid()
            self.set("summary.config.instanceUuid", val.instanceUuid)

        try:
            if not hasattr(val, 'deviceChange'):
                return

            if hasattr(val, 'extraConfig'):
                # there are 2 cases - new entry or update an existing one
                for extra in val.extraConfig:
                    self._update_extra_config(extra)

            if len(val.deviceChange) < 2:
                return

            # Case of Reconfig of VM to attach disk
            controller_key = val.deviceChange[0].device.controllerKey
            filename = val.deviceChange[0].device.backing.fileName

            disk = VirtualDisk()
            disk.controllerKey = controller_key

            disk_backing = VirtualDiskFlatVer2BackingInfo()
            disk_backing.fileName = filename
            disk_backing.key = -101
            disk.backing = disk_backing
            disk.capacityInBytes = 1024
            disk.capacityInKB = 1

            controller = VirtualLsiLogicController()
            controller.key = controller_key

            devices = _create_array_of_type('VirtualDevice')
            devices.VirtualDevice = [disk, controller, self.device[0]]
            self.set("config.hardware.device", devices)
        except AttributeError:
            pass


class Folder(ManagedObject):
    """Folder class."""

    def __init__(self):
        super(Folder, self).__init__("Folder")
        self.set("childEntity", [])


class Network(ManagedObject):
    """Network class."""

    def __init__(self):
        super(Network, self).__init__("network")
        self.set("summary.name", "vmnet0")


class ResourcePool(ManagedObject):
    """Resource Pool class."""

    def __init__(self, name="test_ResPool", value="resgroup-test"):
        super(ResourcePool, self).__init__("rp")
        self.set("name", name)
        summary = DataObject()
        runtime = DataObject()
        config = DataObject()
        memory = DataObject()
        cpu = DataObject()

        memoryAllocation = DataObject()
        cpuAllocation = DataObject()
        vm_list = DataObject()

        memory.maxUsage = 1000 * units.Mi
        memory.overallUsage = 500 * units.Mi
        cpu.maxUsage = 10000
        cpu.overallUsage = 1000
        runtime.cpu = cpu
        runtime.memory = memory
        summary.runtime = runtime
        cpuAllocation.limit = 10000
        memoryAllocation.limit = 1024
        memoryAllocation.reservation = 1024
        config.memoryAllocation = memoryAllocation
        config.cpuAllocation = cpuAllocation
        vm_list.ManagedObjectReference = []
        self.set("summary", summary)
        self.set("summary.runtime.memory", memory)
        self.set("config", config)
        self.set("vm", vm_list)
        parent = ManagedObjectReference(value=value,
                                        name=name)
        owner = ManagedObjectReference(value=value,
                                       name=name)
        self.set("parent", parent)
        self.set("owner", owner)


class DatastoreHostMount(DataObject):
    def __init__(self, value='host-100'):
        super(DatastoreHostMount, self).__init__()
        host_ref = (_db_content["HostSystem"]
                    [list(_db_content["HostSystem"].keys())[0]].obj)
        host_system = DataObject()
        host_system.ManagedObjectReference = [host_ref]
        host_system.value = value
        self.key = host_system


class ClusterComputeResource(ManagedObject):
    """Cluster class."""

    def __init__(self, name="test_cluster"):
        super(ClusterComputeResource, self).__init__("domain")
        self.set("name", name)
        self.set("host", None)
        self.set("datastore", None)
        self.set("resourcePool", None)

        summary = DataObject()
        summary.numHosts = 0
        summary.numCpuCores = 0
        summary.numCpuThreads = 0
        summary.numEffectiveHosts = 0
        summary.totalMemory = 0
        summary.effectiveMemory = 0
        summary.effectiveCpu = 10000
        self.set("summary", summary)

    def _add_root_resource_pool(self, r_pool):
        if r_pool:
            self.set("resourcePool", r_pool)

    def _add_host(self, host_sys):
        if host_sys:
            hosts = self.get("host")
            if hosts is None:
                hosts = DataObject()
                hosts.ManagedObjectReference = []
                self.set("host", hosts)
            hosts.ManagedObjectReference.append(host_sys)
            # Update summary every time a new host is added
            self._update_summary()

    def _add_datastore(self, datastore):
        if datastore:
            datastores = self.get("datastore")
            if datastores is None:
                datastores = DataObject()
                datastores.ManagedObjectReference = []
                self.set("datastore", datastores)
            datastores.ManagedObjectReference.append(datastore)

    # Method to update summary of a cluster upon host addition
    def _update_summary(self):
        summary = self.get("summary")
        summary.numHosts = 0
        summary.numCpuCores = 0
        summary.numCpuThreads = 0
        summary.numEffectiveHosts = 0
        summary.totalMemory = 0
        summary.effectiveMemory = 0

        hosts = self.get("host")
        # Compute the aggregate stats
        summary.numHosts = len(hosts.ManagedObjectReference)
        for host_ref in hosts.ManagedObjectReference:
            host_sys = _get_object(host_ref)
            connected = host_sys.get("connected")
            host_summary = host_sys.get("summary")
            summary.numCpuCores += host_summary.hardware.numCpuCores
            summary.numCpuThreads += host_summary.hardware.numCpuThreads
            summary.totalMemory += host_summary.hardware.memorySize
            free_memory = (host_summary.hardware.memorySize / units.Mi
                           - host_summary.quickStats.overallMemoryUsage)
            summary.effectiveMemory += free_memory if connected else 0
            summary.numEffectiveHosts += 1 if connected else 0
        self.set("summary", summary)


class Datastore(ManagedObject):
    """Datastore class."""

    def __init__(self, name="fake-ds", capacity=1024, free=500,
                 accessible=True, maintenance_mode="normal"):
        super(Datastore, self).__init__("ds")
        self.set("summary.type", "VMFS")
        self.set("summary.name", name)
        self.set("summary.capacity", capacity * units.Gi)
        self.set("summary.freeSpace", free * units.Gi)
        self.set("summary.accessible", accessible)
        self.set("summary.maintenanceMode", maintenance_mode)
        self.set("browser", "")


class HostNetworkSystem(ManagedObject):
    """HostNetworkSystem class."""

    def __init__(self, name="networkSystem"):
        super(HostNetworkSystem, self).__init__("ns")
        self.set("name", name)

        pnic_do = DataObject()
        pnic_do.device = "vmnic0"

        net_info_pnic = DataObject()
        net_info_pnic.PhysicalNic = [pnic_do]

        self.set("networkInfo.pnic", net_info_pnic)


class HostStorageSystem(ManagedObject):
    """HostStorageSystem class."""

    def __init__(self):
        super(HostStorageSystem, self).__init__("storageSystem")


class HostSystem(ManagedObject):
    """Host System class."""

    def __init__(self, name="ha-host", connected=True, ds_ref=None,
                 maintenance_mode=False):
        super(HostSystem, self).__init__("host")
        self.set("name", name)
        if _db_content.get("HostNetworkSystem", None) is None:
            create_host_network_system()
        if not _get_object_refs('HostStorageSystem'):
            create_host_storage_system()
        host_net_key = list(_db_content["HostNetworkSystem"].keys())[0]
        host_net_sys = _db_content["HostNetworkSystem"][host_net_key].obj
        self.set("configManager.networkSystem", host_net_sys)
        host_storage_sys_key = _get_object_refs('HostStorageSystem')[0]
        self.set("configManager.storageSystem", host_storage_sys_key)

        if not ds_ref:
            ds_ref = create_datastore('local-host-%s' % name, 500, 500)
        datastores = DataObject()
        datastores.ManagedObjectReference = [ds_ref]
        self.set("datastore", datastores)

        summary = DataObject()
        hardware = DataObject()
        hardware.numCpuCores = 8
        hardware.numCpuPkgs = 2
        hardware.numCpuThreads = 16
        hardware.vendor = "Intel"
        hardware.cpuModel = "Intel(R) Xeon(R)"
        hardware.uuid = "host-uuid"
        hardware.memorySize = units.Gi
        summary.hardware = hardware

        runtime = DataObject()
        if connected:
            runtime.connectionState = "connected"
        else:
            runtime.connectionState = "disconnected"

        runtime.inMaintenanceMode = maintenance_mode

        summary.runtime = runtime

        quickstats = DataObject()
        quickstats.overallMemoryUsage = 500
        summary.quickStats = quickstats

        product = DataObject()
        product.name = "VMware ESXi"
        product.version = constants.MIN_VC_VERSION
        config = DataObject()
        config.product = product
        summary.config = config

        pnic_do = DataObject()
        pnic_do.device = "vmnic0"
        net_info_pnic = DataObject()
        net_info_pnic.PhysicalNic = [pnic_do]

        self.set("summary", summary)
        self.set("capability.maxHostSupportedVcpus", 600)
        self.set("summary.hardware", hardware)
        self.set("summary.runtime", runtime)
        self.set("config.network.pnic", net_info_pnic)
        self.set("connected", connected)

        if _db_content.get("Network", None) is None:
            create_network()
        net_ref = _db_content["Network"][
            list(_db_content["Network"].keys())[0]].obj
        network_do = DataObject()
        network_do.ManagedObjectReference = [net_ref]
        self.set("network", network_do)

        vswitch_do = DataObject()
        vswitch_do.pnic = ["vmnic0"]
        vswitch_do.name = "vSwitch0"
        vswitch_do.portgroup = ["PortGroup-vmnet0"]

        net_swicth = DataObject()
        net_swicth.HostVirtualSwitch = [vswitch_do]
        self.set("config.network.vswitch", net_swicth)

        host_pg_do = DataObject()
        host_pg_do.key = "PortGroup-vmnet0"

        pg_spec = DataObject()
        pg_spec.vlanId = 0
        pg_spec.name = "vmnet0"

        host_pg_do.spec = pg_spec

        host_pg = DataObject()
        host_pg.HostPortGroup = [host_pg_do]
        self.set("config.network.portgroup", host_pg)

        config = DataObject()
        storageDevice = DataObject()

        iscsi_hba = HostInternetScsiHba()
        iscsi_hba.iScsiName = "iscsi-name"
        host_bus_adapter_array = DataObject()
        host_bus_adapter_array.HostHostBusAdapter = [iscsi_hba]
        storageDevice.hostBusAdapter = host_bus_adapter_array
        config.storageDevice = storageDevice
        self.set("config.storageDevice.hostBusAdapter", host_bus_adapter_array)

        # Set the same on the storage system managed object
        host_storage_sys = _get_object(host_storage_sys_key)
        host_storage_sys.set('storageDeviceInfo.hostBusAdapter',
                             host_bus_adapter_array)

    def _add_iscsi_target(self, data):
        default_lun = DataObject()
        default_lun.scsiLun = 'key-vim.host.ScsiDisk-010'
        default_lun.key = 'key-vim.host.ScsiDisk-010'
        default_lun.deviceName = 'fake-device'
        default_lun.uuid = 'fake-uuid'
        scsi_lun_array = DataObject()
        scsi_lun_array.ScsiLun = [default_lun]
        self.set("config.storageDevice.scsiLun", scsi_lun_array)

        transport = DataObject()
        transport.address = [data['target_portal']]
        transport.iScsiName = data['target_iqn']
        default_target = DataObject()
        default_target.lun = [default_lun]
        default_target.transport = transport

        iscsi_adapter = DataObject()
        iscsi_adapter.adapter = 'key-vmhba33'
        iscsi_adapter.transport = transport
        iscsi_adapter.target = [default_target]
        iscsi_topology = DataObject()
        iscsi_topology.adapter = [iscsi_adapter]
        self.set("config.storageDevice.scsiTopology", iscsi_topology)

    def _add_port_group(self, spec):
        """Adds a port group to the host system object in the db."""
        pg_name = spec.name
        vswitch_name = spec.vswitchName
        vlanid = spec.vlanId

        vswitch_do = DataObject()
        vswitch_do.pnic = ["vmnic0"]
        vswitch_do.name = vswitch_name
        vswitch_do.portgroup = ["PortGroup-%s" % pg_name]

        vswitches = self.get("config.network.vswitch").HostVirtualSwitch
        vswitches.append(vswitch_do)

        host_pg_do = DataObject()
        host_pg_do.key = "PortGroup-%s" % pg_name

        pg_spec = DataObject()
        pg_spec.vlanId = vlanid
        pg_spec.name = pg_name

        host_pg_do.spec = pg_spec
        host_pgrps = self.get("config.network.portgroup").HostPortGroup
        host_pgrps.append(host_pg_do)


class Datacenter(ManagedObject):
    """Datacenter class."""

    def __init__(self, name="ha-datacenter", ds_ref=None):
        super(Datacenter, self).__init__("dc")
        self.set("name", name)
        if _db_content.get("Folder", None) is None:
            create_folder()
        folder_ref = _db_content["Folder"][
            list(_db_content["Folder"].keys())[0]].obj
        folder_do = DataObject()
        folder_do.ManagedObjectReference = [folder_ref]
        self.set("vmFolder", folder_ref)
        if _db_content.get("Network", None) is None:
            create_network()
        net_ref = _db_content["Network"][
            list(_db_content["Network"].keys())[0]].obj
        network_do = DataObject()
        network_do.ManagedObjectReference = [net_ref]
        self.set("network", network_do)
        if ds_ref:
            datastore = DataObject()
            datastore.ManagedObjectReference = [ds_ref]
        else:
            datastore = None
        self.set("datastore", datastore)


class Task(ManagedObject):
    """Task class."""

    def __init__(self, task_name, state="running", result=None,
                 error_fault=None):
        super(Task, self).__init__("Task")
        info = DataObject()
        info.name = task_name
        info.state = state
        if state == 'error':
            error = DataObject()
            error.localizedMessage = "Error message"
            if not error_fault:
                error.fault = DataObject()
            else:
                error.fault = error_fault
            info.error = error
        info.result = result
        self.set("info", info)


def create_host_network_system():
    host_net_system = HostNetworkSystem()
    _create_object("HostNetworkSystem", host_net_system)


def create_host_storage_system():
    host_storage_system = HostStorageSystem()
    _create_object("HostStorageSystem", host_storage_system)


def create_host(ds_ref=None):
    host_system = HostSystem(ds_ref=ds_ref)
    _create_object('HostSystem', host_system)


def create_datacenter(name, ds_ref=None):
    data_center = Datacenter(name, ds_ref)
    _create_object('Datacenter', data_center)


def create_datastore(name, capacity, free):
    data_store = Datastore(name, capacity, free)
    _create_object('Datastore', data_store)
    return data_store.obj


def create_res_pool():
    res_pool = ResourcePool()
    _create_object('ResourcePool', res_pool)
    return res_pool.obj


def create_folder():
    folder = Folder()
    _create_object('Folder', folder)
    return folder.obj


def create_network():
    network = Network()
    _create_object('Network', network)


def create_cluster(name, ds_ref):
    cluster = ClusterComputeResource(name=name)
    cluster._add_host(_get_object_refs("HostSystem")[0])
    cluster._add_host(_get_object_refs("HostSystem")[1])
    cluster._add_datastore(ds_ref)
    cluster._add_root_resource_pool(create_res_pool())
    _create_object('ClusterComputeResource', cluster)
    return cluster


def create_vm(uuid=None, name=None,
              cpus=1, memory=128, devices=None,
              vmPathName=None, extraConfig=None,
              res_pool_ref=None, host_ref=None,
              version=None):
    if uuid is None:
        uuid = uuidutils.generate_uuid()

    if name is None:
        name = uuid

    if devices is None:
        devices = []

    if vmPathName is None:
        vm_path = ds_obj.DatastorePath(
            list(_db_content['Datastore'].values())[0])
    else:
        vm_path = ds_obj.DatastorePath.parse(vmPathName)

    if res_pool_ref is None:
        res_pool_ref = list(_db_content['ResourcePool'].keys())[0]

    if host_ref is None:
        host_ref = list(_db_content["HostSystem"].keys())[0]

    # Fill in the default path to the vmx file if we were only given a
    # datastore. Note that if you create a VM with vmPathName '[foo]', when you
    # retrieve vmPathName it will be '[foo] uuid/uuid.vmx'. Hence we use
    # vm_path below for the stored value of vmPathName.
    if vm_path.rel_path == '':
        vm_path = vm_path.join(name, name + '.vmx')

    for key, value in six.iteritems(_db_content["Datastore"]):
        if value.get('summary.name') == vm_path.datastore:
            ds = key
            break
    else:
        ds = create_datastore(vm_path.datastore, 1024, 500)

    vm_dict = {"name": name,
              "ds": [ds],
              "runtime_host": host_ref,
              "powerstate": "poweredOff",
              "vmPathName": str(vm_path),
              "numCpu": cpus,
              "mem": memory,
              "extra_config": extraConfig,
              "virtual_device": devices,
              "instanceUuid": uuid,
              "version": version}
    vm = VirtualMachine(**vm_dict)
    _create_object("VirtualMachine", vm)

    res_pool = _get_object(res_pool_ref)
    res_pool.vm.ManagedObjectReference.append(vm.obj)

    return vm.obj


def create_task(task_name, state="running", result=None, error_fault=None):
    task = Task(task_name, state, result, error_fault)
    _create_object("Task", task)
    return task


def _add_file(file_path):
    """Adds a file reference to the  db."""
    _db_content["files"].append(file_path)


def _remove_file(file_path):
    """Removes a file reference from the db."""
    # Check if the remove is for a single file object or for a folder
    if file_path.find(".vmdk") != -1:
        if file_path not in _db_content.get("files"):
            raise vexc.FileNotFoundException(file_path)
        _db_content.get("files").remove(file_path)
    else:
        # Removes the files in the folder and the folder too from the db
        to_delete = set()
        for file in _db_content.get("files"):
            if file.find(file_path) != -1:
                to_delete.add(file)
        for file in to_delete:
            _db_content.get("files").remove(file)


def fake_plug_vifs(*args, **kwargs):
    """Fakes plugging vifs."""
    pass


def fake_get_network(*args, **kwargs):
    """Fake get network."""
    return {'type': 'fake'}


def assertPathExists(test, path):
    test.assertIn(path, _db_content.get('files'))


def assertPathNotExists(test, path):
    test.assertNotIn(path, _db_content.get('files'))


def get_file(file_path):
    """Check if file exists in the db."""
    return file_path in _db_content.get("files")


def fake_upload_image(context, image, instance, **kwargs):
    """Fakes the upload of an image."""
    pass


def fake_fetch_image(context, instance, host, port, dc_name, ds_name,
                     file_path, cookies=None):
    """Fakes the fetch of an image."""
    ds_file_path = "[" + ds_name + "] " + file_path
    _add_file(ds_file_path)


def _get_vm_mdo(vm_ref):
    """Gets the Virtual Machine with the ref from the db."""
    if _db_content.get("VirtualMachine", None) is None:
            raise exception.NotFound("There is no VM registered")
    if vm_ref not in _db_content.get("VirtualMachine"):
        raise exception.NotFound("Virtual Machine with ref %s is not "
                                 "there" % vm_ref)
    return _db_content.get("VirtualMachine")[vm_ref]


def _merge_extraconfig(existing, changes):
    """Imposes the changes in extraConfig over the existing extraConfig."""
    existing = existing or []
    if (changes):
        for c in changes:
            if len([x for x in existing if x.key == c.key]) > 0:
                extraConf = [x for x in existing if x.key == c.key][0]
                extraConf.value = c.value
            else:
                existing.append(c)
    return existing


class FakeFactory(object):
    """Fake factory class for the suds client."""

    def create(self, obj_name):
        """Creates a namespace object."""
        klass = obj_name[4:]  # skip 'ns0:'
        module = sys.modules[__name__]
        fake_klass = getattr(module, klass, None)
        if fake_klass is None:
            return DataObject(obj_name)
        else:
            return fake_klass()


class SharesInfo(DataObject):
    def __init__(self):
        super(SharesInfo, self).__init__()
        self.level = None
        self.shares = None


class VirtualEthernetCardResourceAllocation(DataObject):
    def __init__(self):
        super(VirtualEthernetCardResourceAllocation, self).__init__()
        self.share = SharesInfo()


class VirtualE1000(DataObject):
    def __init__(self):
        super(VirtualE1000, self).__init__()
        self.resourceAllocation = VirtualEthernetCardResourceAllocation()


class FakeService(DataObject):
    """Fake service class."""

    def Logout(self, session_manager):
        pass

    def FindExtension(self, extension_manager, key):
        return []


class FakeClient(DataObject):
    """Fake client class."""

    def __init__(self):
        """Creates a namespace object."""
        self.service = FakeService()


class FakeSession(object):
    """Fake Session Class."""

    def __init__(self):
        self.vim = FakeVim()

    def _call_method(self, module, method, *args, **kwargs):
        raise NotImplementedError()

    def _wait_for_task(self, task_ref):
        raise NotImplementedError()


class FakeObjectRetrievalSession(FakeSession):
    """A session for faking object retrieval tasks.

    _call_method() returns a given set of objects
    sequentially, regardless of the method called.
    """

    def __init__(self, *ret):
        super(FakeObjectRetrievalSession, self).__init__()
        self.ret = ret
        self.ind = 0

    def _call_method(self, module, method, *args, **kwargs):
        if (method == 'continue_retrieval' or
            method == 'cancel_retrieval'):
            return
        # return fake objects in a circular manner
        self.ind = (self.ind + 1) % len(self.ret)
        return self.ret[self.ind - 1]


def get_fake_vim_object(vmware_api_session):
    key = vmware_api_session.__repr__()
    if key not in _vim_map:
        _vim_map[key] = FakeVim()
    return _vim_map[key]


class FakeVim(object):
    """Fake VIM Class."""

    def __init__(self, protocol="https", host="localhost", trace=None):
        """Initializes the suds client object, sets the service content
        contents and the cookies for the session.
        """
        self._session = None
        self.client = FakeClient()
        self.client.factory = FakeFactory()

        transport = DataObject()
        transport.cookiejar = "Fake-CookieJar"
        options = DataObject()
        options.transport = transport

        self.client.options = options

        service_content = self.client.factory.create('ns0:ServiceContent')
        service_content.propertyCollector = "PropCollector"
        service_content.virtualDiskManager = "VirtualDiskManager"
        service_content.fileManager = "FileManager"
        service_content.rootFolder = "RootFolder"
        service_content.sessionManager = "SessionManager"
        service_content.extensionManager = "ExtensionManager"
        service_content.searchIndex = "SearchIndex"

        about_info = DataObject()
        about_info.name = "VMware vCenter Server"
        about_info.version = "5.1.0"
        about_info.instanceUuid = _FAKE_VCENTER_UUID

        service_content.about = about_info

        self._service_content = service_content

    @property
    def service_content(self):
        return self._service_content

    def __repr__(self):
        return "Fake VIM Object"

    def __str__(self):
        return "Fake VIM Object"

    def _login(self):
        """Logs in and sets the session object in the db."""
        self._session = uuidutils.generate_uuid()
        session = DataObject()
        session.key = self._session
        session.userName = 'sessionUserName'
        _db_content['session'][self._session] = session
        return session

    def _terminate_session(self, *args, **kwargs):
        """Terminates a session."""
        s = kwargs.get("sessionId")[0]
        if s not in _db_content['session']:
            return
        del _db_content['session'][s]

    def _check_session(self):
        """Checks if the session is active."""
        if (self._session is None or self._session not in
                 _db_content['session']):
            LOG.debug("Session is faulty")
            raise vexc.VimFaultException([vexc.NOT_AUTHENTICATED],
                                         "Session Invalid")

    def _session_is_active(self, *args, **kwargs):
        try:
            self._check_session()
            return True
        except Exception:
            return False

    def _create_vm(self, method, *args, **kwargs):
        """Creates and registers a VM object with the Host System."""
        config_spec = kwargs.get("config")

        if config_spec.guestId not in constants.VALID_OS_TYPES:
            ex = vexc.VMwareDriverException('A specified parameter was '
                                            'not correct.')
            return create_task(method, "error", error_fault=ex).obj

        pool = kwargs.get('pool')
        version = getattr(config_spec, 'version', None)
        devices = []
        for device_change in config_spec.deviceChange:
            if device_change.operation == 'add':
                devices.append(device_change.device)

        vm_ref = create_vm(config_spec.instanceUuid, config_spec.name,
                           config_spec.numCPUs, config_spec.memoryMB,
                           devices, config_spec.files.vmPathName,
                           config_spec.extraConfig, pool,
                           version=version)

        task_mdo = create_task(method, "success", result=vm_ref)
        return task_mdo.obj

    def _create_folder(self, method, *args, **kwargs):
        return create_folder()

    def _reconfig_vm(self, method, *args, **kwargs):
        """Reconfigures a VM and sets the properties supplied."""
        vm_ref = args[0]
        vm_mdo = _get_vm_mdo(vm_ref)
        vm_mdo.reconfig(self.client.factory, kwargs.get("spec"))
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _rename(self, method, *args, **kwargs):
        vm_ref = args[0]
        vm_mdo = _get_vm_mdo(vm_ref)
        vm_mdo.set('name', kwargs['newName'])
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _create_copy_disk(self, method, vmdk_file_path):
        """Creates/copies a vmdk file object in the datastore."""
        # We need to add/create both .vmdk and .-flat.vmdk files
        flat_vmdk_file_path = vmdk_file_path.replace(".vmdk", "-flat.vmdk")
        _add_file(vmdk_file_path)
        _add_file(flat_vmdk_file_path)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _extend_disk(self, method, size):
        """Extend disk size when create an instance."""
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _snapshot_vm(self, method):
        """Snapshots a VM. Here we do nothing for faking sake."""
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _find_all_by_uuid(self, *args, **kwargs):
        uuid = kwargs.get('uuid')
        vm_refs = []
        for vm_ref in _db_content.get("VirtualMachine"):
            vm = _get_object(vm_ref)
            vm_uuid = vm.get("summary.config.instanceUuid")
            if vm_uuid == uuid:
                vm_refs.append(vm_ref)
        return vm_refs

    def _delete_snapshot(self, method, *args, **kwargs):
        """Deletes a VM snapshot. Here we do nothing for faking sake."""
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _delete_file(self, method, *args, **kwargs):
        """Deletes a file from the datastore."""
        _remove_file(kwargs.get("name"))
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _just_return(self):
        """Fakes a return."""
        return

    def _just_return_task(self, method):
        """Fakes a task return."""
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _clone_vm(self, method, *args, **kwargs):
        """Fakes a VM clone."""
        """Creates and registers a VM object with the Host System."""
        source_vmref = args[0]
        source_vm_mdo = _get_vm_mdo(source_vmref)
        clone_spec = kwargs.get("spec")
        vm_dict = {
         "name": kwargs.get("name"),
         "ds": source_vm_mdo.get("datastore"),
         "runtime_host": source_vm_mdo.get("runtime.host"),
         "powerstate": source_vm_mdo.get("runtime.powerState"),
         "vmPathName": source_vm_mdo.get("config.files.vmPathName"),
         "numCpu": source_vm_mdo.get("summary.config.numCpu"),
         "mem": source_vm_mdo.get("summary.config.memorySizeMB"),
         "extra_config": source_vm_mdo.get("config.extraConfig").OptionValue,
         "virtual_device":
             source_vm_mdo.get("config.hardware.device").VirtualDevice,
         "instanceUuid": source_vm_mdo.get("summary.config.instanceUuid")}

        if hasattr(clone_spec, 'config'):
            # Impose the config changes specified in the config property
            if (hasattr(clone_spec.config, 'instanceUuid') and
               clone_spec.config.instanceUuid is not None):
                vm_dict["instanceUuid"] = clone_spec.config.instanceUuid

            if hasattr(clone_spec.config, 'extraConfig'):
                extraConfigs = _merge_extraconfig(vm_dict["extra_config"],
                                                clone_spec.config.extraConfig)
                vm_dict["extra_config"] = extraConfigs

        virtual_machine = VirtualMachine(**vm_dict)
        _create_object("VirtualMachine", virtual_machine)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _unregister_vm(self, method, *args, **kwargs):
        """Unregisters a VM from the Host System."""
        vm_ref = args[0]
        _get_vm_mdo(vm_ref)
        del _db_content["VirtualMachine"][vm_ref]
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _search_ds(self, method, *args, **kwargs):
        """Searches the datastore for a file."""
        # TODO(garyk): add support for spec parameter
        ds_path = kwargs.get("datastorePath")
        matched_files = set()
        # Check if we are searching for a file or a directory
        directory = False
        dname = '%s/' % ds_path
        for file in _db_content.get("files"):
            if file == dname:
                directory = True
                break
        # A directory search implies that we must return all
        # subdirectories
        if directory:
            for file in _db_content.get("files"):
                if file.find(ds_path) != -1:
                    if not file.endswith(ds_path):
                        path = file.replace(dname, '', 1).split('/')
                        if path:
                            matched_files.add(path[0])
            if not matched_files:
                matched_files.add('/')
        else:
            for file in _db_content.get("files"):
                if file.find(ds_path) != -1:
                    matched_files.add(ds_path)
        if matched_files:
            result = DataObject()
            result.path = ds_path
            result.file = []
            for file in matched_files:
                matched = DataObject()
                matched.path = file
                matched.fileSize = 1024
                result.file.append(matched)
            task_mdo = create_task(method, "success", result=result)
        else:
            task_mdo = create_task(method, "error", error_fault=FileNotFound())
        return task_mdo.obj

    def _move_file(self, method, *args, **kwargs):
        source = kwargs.get('sourceName')
        destination = kwargs.get('destinationName')
        new_files = []
        if source != destination:
            for file in _db_content.get("files"):
                if source in file:
                    new_file = file.replace(source, destination)
                    new_files.append(new_file)
            # if source is not a file then the children will also
            # be deleted
            _remove_file(source)
        for file in new_files:
            _add_file(file)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _make_dir(self, method, *args, **kwargs):
        """Creates a directory in the datastore."""
        ds_path = kwargs.get("name")
        if get_file(ds_path):
            raise vexc.FileAlreadyExistsException()
        _db_content["files"].append('%s/' % ds_path)

    def _set_power_state(self, method, vm_ref, pwr_state="poweredOn"):
        """Sets power state for the VM."""
        if _db_content.get("VirtualMachine", None) is None:
            raise exception.NotFound("No Virtual Machine has been "
                                     "registered yet")
        if vm_ref not in _db_content.get("VirtualMachine"):
            raise exception.NotFound("Virtual Machine with ref %s is not "
                                     "there" % vm_ref)
        vm_mdo = _db_content.get("VirtualMachine").get(vm_ref)
        vm_mdo.set("runtime.powerState", pwr_state)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _retrieve_properties_continue(self, method, *args, **kwargs):
        """Continues the retrieve."""
        return FakeRetrieveResult()

    def _retrieve_properties_cancel(self, method, *args, **kwargs):
        """Cancels the retrieve."""
        return None

    def _retrieve_properties(self, method, *args, **kwargs):
        """Retrieves properties based on the type."""
        spec_set = kwargs.get("specSet")[0]
        spec_type = spec_set.propSet[0].type
        properties = spec_set.propSet[0].pathSet
        if not isinstance(properties, list):
            properties = properties.split()
        objs = spec_set.objectSet
        lst_ret_objs = FakeRetrieveResult()
        for obj in objs:
            try:
                obj_ref = obj.obj
                if obj_ref == "RootFolder":
                    # This means that we are retrieving props for all managed
                    # data objects of the specified 'type' in the entire
                    # inventory. This gets invoked by vim_util.get_objects.
                    mdo_refs = _db_content[spec_type]
                elif obj_ref.type != spec_type:
                    # This means that we are retrieving props for the managed
                    # data objects in the parent object's 'path' property.
                    # This gets invoked by vim_util.get_inner_objects
                    # eg. obj_ref = <ManagedObjectReference of a cluster>
                    #     type = 'DataStore'
                    #     path = 'datastore'
                    # the above will retrieve all datastores in the given
                    # cluster.
                    parent_mdo = _db_content[obj_ref.type][obj_ref]
                    path = obj.selectSet[0].path
                    mdo_refs = parent_mdo.get(path).ManagedObjectReference
                else:
                    # This means that we are retrieving props of the given
                    # managed data object. This gets invoked by
                    # vim_util.get_properties_for_a_collection_of_objects.
                    mdo_refs = [obj_ref]

                for mdo_ref in mdo_refs:
                    mdo = _db_content[spec_type][mdo_ref]
                    prop_list = []
                    for prop_name in properties:
                        prop = Prop(prop_name, mdo.get(prop_name))
                        prop_list.append(prop)
                    obj_content = ObjectContent(mdo.obj, prop_list)
                    lst_ret_objs.add_object(obj_content)
            except Exception:
                LOG.exception("_retrieve_properties error")
                continue
        return lst_ret_objs

    def _add_port_group(self, method, *args, **kwargs):
        """Adds a port group to the host system."""
        _host_sk = list(_db_content["HostSystem"].keys())[0]
        host_mdo = _db_content["HostSystem"][_host_sk]
        host_mdo._add_port_group(kwargs.get("portgrp"))

    def _add_iscsi_send_tgt(self, method, *args, **kwargs):
        """Adds a iscsi send target to the hba."""
        send_targets = kwargs.get('targets')
        host_storage_sys = _get_objects('HostStorageSystem').objects[0]
        iscsi_hba_array = host_storage_sys.get('storageDeviceInfo'
                                               '.hostBusAdapter')
        iscsi_hba = iscsi_hba_array.HostHostBusAdapter[0]
        if hasattr(iscsi_hba, 'configuredSendTarget'):
            iscsi_hba.configuredSendTarget.extend(send_targets)
        else:
            iscsi_hba.configuredSendTarget = send_targets

    def __getattr__(self, attr_name):
        if attr_name != "Login":
            self._check_session()
        if attr_name == "Login":
            return lambda *args, **kwargs: self._login()
        elif attr_name == "SessionIsActive":
            return lambda *args, **kwargs: self._session_is_active(
                                               *args, **kwargs)
        elif attr_name == "TerminateSession":
            return lambda *args, **kwargs: self._terminate_session(
                                               *args, **kwargs)
        elif attr_name == "CreateVM_Task":
            return lambda *args, **kwargs: self._create_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "CreateFolder":
            return lambda *args, **kwargs: self._create_folder(attr_name,
                                                *args, **kwargs)
        elif attr_name == "ReconfigVM_Task":
            return lambda *args, **kwargs: self._reconfig_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "Rename_Task":
            return lambda *args, **kwargs: self._rename(attr_name,
                                                *args, **kwargs)
        elif attr_name == "CreateVirtualDisk_Task":
            return lambda *args, **kwargs: self._create_copy_disk(attr_name,
                                                kwargs.get("name"))
        elif attr_name == "DeleteDatastoreFile_Task":
            return lambda *args, **kwargs: self._delete_file(attr_name,
                                                *args, **kwargs)
        elif attr_name == "PowerOnVM_Task":
            return lambda *args, **kwargs: self._set_power_state(attr_name,
                                                args[0], "poweredOn")
        elif attr_name == "PowerOffVM_Task":
            return lambda *args, **kwargs: self._set_power_state(attr_name,
                                                args[0], "poweredOff")
        elif attr_name == "RebootGuest":
            return lambda *args, **kwargs: self._just_return()
        elif attr_name == "ResetVM_Task":
            return lambda *args, **kwargs: self._set_power_state(attr_name,
                                                args[0], "poweredOn")
        elif attr_name == "SuspendVM_Task":
            return lambda *args, **kwargs: self._set_power_state(attr_name,
                                                args[0], "suspended")
        elif attr_name == "CreateSnapshot_Task":
            return lambda *args, **kwargs: self._snapshot_vm(attr_name)
        elif attr_name == "RemoveSnapshot_Task":
            return lambda *args, **kwargs: self._delete_snapshot(attr_name,
                                                *args, **kwargs)
        elif attr_name == "CopyVirtualDisk_Task":
            return lambda *args, **kwargs: self._create_copy_disk(attr_name,
                                                kwargs.get("destName"))
        elif attr_name == "ExtendVirtualDisk_Task":
            return lambda *args, **kwargs: self._extend_disk(attr_name,
                                                kwargs.get("size"))
        elif attr_name == "Destroy_Task":
            return lambda *args, **kwargs: self._unregister_vm(attr_name,
                                                               *args, **kwargs)
        elif attr_name == "UnregisterVM":
            return lambda *args, **kwargs: self._unregister_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "CloneVM_Task":
            return lambda *args, **kwargs: self._clone_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "FindAllByUuid":
            return lambda *args, **kwargs: self._find_all_by_uuid(attr_name,
                                                *args, **kwargs)
        elif attr_name == "SearchDatastore_Task":
            return lambda *args, **kwargs: self._search_ds(attr_name,
                                                *args, **kwargs)
        elif attr_name == "MoveDatastoreFile_Task":
            return lambda *args, **kwargs: self._move_file(attr_name,
                                                *args, **kwargs)
        elif attr_name == "MakeDirectory":
            return lambda *args, **kwargs: self._make_dir(attr_name,
                                                *args, **kwargs)
        elif attr_name == "RetrievePropertiesEx":
            return lambda *args, **kwargs: self._retrieve_properties(
                                                attr_name, *args, **kwargs)
        elif attr_name == "ContinueRetrievePropertiesEx":
            return lambda *args, **kwargs: self._retrieve_properties_continue(
                                                attr_name, *args, **kwargs)
        elif attr_name == "CancelRetrievePropertiesEx":
            return lambda *args, **kwargs: self._retrieve_properties_cancel(
                                                attr_name, *args, **kwargs)
        elif attr_name == "AddPortGroup":
            return lambda *args, **kwargs: self._add_port_group(attr_name,
                                                *args, **kwargs)
        elif attr_name in ("RebootHost_Task",
                           "ShutdownHost_Task",
                           "PowerUpHostFromStandBy_Task",
                           "EnterMaintenanceMode_Task",
                           "ExitMaintenanceMode_Task",
                           "RescanHba"):
            return lambda *args, **kwargs: self._just_return_task(attr_name)
        elif attr_name == "AddInternetScsiSendTargets":
            return lambda *args, **kwargs: self._add_iscsi_send_tgt(attr_name,
                                                *args, **kwargs)
