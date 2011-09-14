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
A fake VMWare VI API implementation.
"""

from pprint import pformat
import uuid

from nova import exception
from nova import log as logging
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import error_util

_CLASSES = ['Datacenter', 'Datastore', 'ResourcePool', 'VirtualMachine',
            'Network', 'HostSystem', 'HostNetworkSystem', 'Task', 'session',
            'files']

_FAKE_FILE_SIZE = 1024

_db_content = {}

LOG = logging.getLogger("nova.virt.vmwareapi.fake")


def log_db_contents(msg=None):
    """Log DB Contents."""
    text = msg or ""
    content = pformat(_db_content)
    LOG.debug(_("%(text)s: _db_content => %(content)s") % locals())


def reset():
    """Resets the db contents."""
    for c in _CLASSES:
        # We fake the datastore by keeping the file references as a list of
        # names in the db
        if c == 'files':
            _db_content[c] = []
        else:
            _db_content[c] = {}
    create_network()
    create_host_network_system()
    create_host()
    create_datacenter()
    create_datastore()
    create_res_pool()


def cleanup():
    """Clear the db contents."""
    for c in _CLASSES:
        _db_content[c] = {}


def _create_object(table, table_obj):
    """Create an object in the db."""
    _db_content[table][table_obj.obj] = table_obj


def _get_objects(obj_type):
    """Get objects of the type."""
    lst_objs = []
    for key in _db_content[obj_type]:
        lst_objs.append(_db_content[obj_type][key])
    return lst_objs


class Prop(object):
    """Property Object base class."""

    def __init__(self):
        self.name = None
        self.val = None


class ManagedObject(object):
    """Managed Data Object base class."""

    def __init__(self, name="ManagedObject", obj_ref=None):
        """Sets the obj property which acts as a reference to the object."""
        super(ManagedObject, self).__setattr__('objName', name)
        if obj_ref is None:
            obj_ref = str(uuid.uuid4())
        object.__setattr__(self, 'obj', obj_ref)
        object.__setattr__(self, 'propSet', [])

    def set(self, attr, val):
        """
        Sets an attribute value. Not using the __setattr__ directly for we
        want to set attributes of the type 'a.b.c' and using this function
        class we set the same.
        """
        self.__setattr__(attr, val)

    def get(self, attr):
        """
        Gets an attribute. Used as an intermediary to get nested
        property like 'a.b.c' value.
        """
        return self.__getattr__(attr)

    def __setattr__(self, attr, val):
        for prop in self.propSet:
            if prop.name == attr:
                prop.val = val
                return
        elem = Prop()
        elem.name = attr
        elem.val = val
        self.propSet.append(elem)

    def __getattr__(self, attr):
        for elem in self.propSet:
            if elem.name == attr:
                return elem.val
        raise exception.Error(_("Property %(attr)s not set for the managed "
                        "object %(objName)s") %
                        {'attr': attr,
                         'objName': self.objName})


class DataObject(object):
    """Data object base class."""
    pass


class VirtualDisk(DataObject):
    """
    Virtual Disk class. Does nothing special except setting
    __class__.__name__ to 'VirtualDisk'. Refer place where __class__.__name__
    is used in the code.
    """
    pass


class VirtualDiskFlatVer2BackingInfo(DataObject):
    """VirtualDiskFlatVer2BackingInfo class."""
    pass


class VirtualLsiLogicController(DataObject):
    """VirtualLsiLogicController class."""
    pass


class VirtualMachine(ManagedObject):
    """Virtual Machine class."""

    def __init__(self, **kwargs):
        super(VirtualMachine, self).__init__("VirtualMachine")
        self.set("name", kwargs.get("name"))
        self.set("runtime.connectionState",
                 kwargs.get("conn_state", "connected"))
        self.set("summary.config.guestId", kwargs.get("guest", "otherGuest"))
        ds_do = DataObject()
        ds_do.ManagedObjectReference = [kwargs.get("ds").obj]
        self.set("datastore", ds_do)
        self.set("summary.guest.toolsStatus", kwargs.get("toolsstatus",
                                "toolsOk"))
        self.set("summary.guest.toolsRunningStatus", kwargs.get(
                                "toolsrunningstate", "guestToolsRunning"))
        self.set("runtime.powerState", kwargs.get("powerstate", "poweredOn"))
        self.set("config.files.vmPathName", kwargs.get("vmPathName"))
        self.set("summary.config.numCpu", kwargs.get("numCpu", 1))
        self.set("summary.config.memorySizeMB", kwargs.get("mem", 1))
        self.set("config.hardware.device", kwargs.get("virtual_disk", None))
        self.set("config.extraConfig", kwargs.get("extra_config", None))

    def reconfig(self, factory, val):
        """
        Called to reconfigure the VM. Actually customizes the property
        setting of the Virtual Machine object.
        """
        try:
            # Case of Reconfig of VM to attach disk
            controller_key = val.deviceChange[1].device.controllerKey
            filename = val.deviceChange[1].device.backing.fileName

            disk = VirtualDisk()
            disk.controllerKey = controller_key

            disk_backing = VirtualDiskFlatVer2BackingInfo()
            disk_backing.fileName = filename
            disk_backing.key = -101
            disk.backing = disk_backing

            controller = VirtualLsiLogicController()
            controller.key = controller_key

            self.set("config.hardware.device", [disk, controller])
        except AttributeError:
            # Case of Reconfig of VM to set extra params
            self.set("config.extraConfig", val.extraConfig)


class Network(ManagedObject):
    """Network class."""

    def __init__(self):
        super(Network, self).__init__("Network")
        self.set("summary.name", "vmnet0")


class ResourcePool(ManagedObject):
    """Resource Pool class."""

    def __init__(self):
        super(ResourcePool, self).__init__("ResourcePool")
        self.set("name", "ResPool")


class Datastore(ManagedObject):
    """Datastore class."""

    def __init__(self):
        super(Datastore, self).__init__("Datastore")
        self.set("summary.type", "VMFS")
        self.set("summary.name", "fake-ds")


class HostNetworkSystem(ManagedObject):
    """HostNetworkSystem class."""

    def __init__(self):
        super(HostNetworkSystem, self).__init__("HostNetworkSystem")
        self.set("name", "networkSystem")

        pnic_do = DataObject()
        pnic_do.device = "vmnic0"

        net_info_pnic = DataObject()
        net_info_pnic.PhysicalNic = [pnic_do]

        self.set("networkInfo.pnic", net_info_pnic)


class HostSystem(ManagedObject):
    """Host System class."""

    def __init__(self):
        super(HostSystem, self).__init__("HostSystem")
        self.set("name", "ha-host")
        if _db_content.get("HostNetworkSystem", None) is None:
            create_host_network_system()
        host_net_key = _db_content["HostNetworkSystem"].keys()[0]
        host_net_sys = _db_content["HostNetworkSystem"][host_net_key].obj
        self.set("configManager.networkSystem", host_net_sys)

        if _db_content.get("Network", None) is None:
            create_network()
        net_ref = _db_content["Network"][_db_content["Network"].keys()[0]].obj
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

    def __init__(self):
        super(Datacenter, self).__init__("Datacenter")
        self.set("name", "ha-datacenter")
        self.set("vmFolder", "vm_folder_ref")
        if _db_content.get("Network", None) is None:
            create_network()
        net_ref = _db_content["Network"][_db_content["Network"].keys()[0]].obj
        network_do = DataObject()
        network_do.ManagedObjectReference = [net_ref]
        self.set("network", network_do)


class Task(ManagedObject):
    """Task class."""

    def __init__(self, task_name, state="running"):
        super(Task, self).__init__("Task")
        info = DataObject
        info.name = task_name
        info.state = state
        self.set("info", info)


def create_host_network_system():
    host_net_system = HostNetworkSystem()
    _create_object("HostNetworkSystem", host_net_system)


def create_host():
    host_system = HostSystem()
    _create_object('HostSystem', host_system)


def create_datacenter():
    data_center = Datacenter()
    _create_object('Datacenter', data_center)


def create_datastore():
    data_store = Datastore()
    _create_object('Datastore', data_store)


def create_res_pool():
    res_pool = ResourcePool()
    _create_object('ResourcePool', res_pool)


def create_network():
    network = Network()
    _create_object('Network', network)


def create_task(task_name, state="running"):
    task = Task(task_name, state)
    _create_object("Task", task)
    return task


def _add_file(file_path):
    """Adds a file reference to the  db."""
    _db_content["files"].append(file_path)


def _remove_file(file_path):
    """Removes a file reference from the db."""
    if _db_content.get("files") is None:
        raise exception.NoFilesFound()
    # Check if the remove is for a single file object or for a folder
    if file_path.find(".vmdk") != -1:
        if file_path not in _db_content.get("files"):
            raise exception.FileNotFound(file_path=file_path)
        _db_content.get("files").remove(file_path)
    else:
        # Removes the files in the folder and the folder too from the db
        for file in _db_content.get("files"):
            if file.find(file_path) != -1:
                lst_files = _db_content.get("files")
                if lst_files and lst_files.count(file):
                    lst_files.remove(file)


def fake_plug_vifs(*args, **kwargs):
    """Fakes plugging vifs."""
    pass


def fake_get_network(*args, **kwargs):
    """Fake get network."""
    return {'type': 'fake'}


def fake_fetch_image(context, image, instance, **kwargs):
    """Fakes fetch image call. Just adds a reference to the db for the file."""
    ds_name = kwargs.get("datastore_name")
    file_path = kwargs.get("file_path")
    ds_file_path = "[" + ds_name + "] " + file_path
    _add_file(ds_file_path)


def fake_upload_image(context, image, instance, **kwargs):
    """Fakes the upload of an image."""
    pass


def fake_get_vmdk_size_and_properties(context, image_id, instance):
    """Fakes the file size and properties fetch for the image file."""
    props = {"vmware_ostype": "otherGuest",
            "vmware_adaptertype": "lsiLogic"}
    return _FAKE_FILE_SIZE, props


def _get_vm_mdo(vm_ref):
    """Gets the Virtual Machine with the ref from the db."""
    if _db_content.get("VirtualMachine", None) is None:
            raise exception.NotFound(_("There is no VM registered"))
    if vm_ref not in _db_content.get("VirtualMachine"):
        raise exception.NotFound(_("Virtual Machine with ref %s is not "
                        "there") % vm_ref)
    return _db_content.get("VirtualMachine")[vm_ref]


class FakeFactory(object):
    """Fake factory class for the suds client."""

    def create(self, obj_name):
        """Creates a namespace object."""
        return DataObject()


class FakeVim(object):
    """Fake VIM Class."""

    def __init__(self, protocol="https", host="localhost", trace=None):
        """
        Initializes the suds client object, sets the service content
        contents and the cookies for the session.
        """
        self._session = None
        self.client = DataObject()
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
        self._service_content = service_content

    def get_service_content(self):
        return self._service_content

    def __repr__(self):
        return "Fake VIM Object"

    def __str__(self):
        return "Fake VIM Object"

    def _login(self):
        """Logs in and sets the session object in the db."""
        self._session = str(uuid.uuid4())
        session = DataObject()
        session.key = self._session
        _db_content['session'][self._session] = session
        return session

    def _logout(self):
        """Logs out and remove the session object ref from the db."""
        s = self._session
        self._session = None
        if s not in _db_content['session']:
            raise exception.Error(
                _("Logging out a session that is invalid or already logged "
                "out: %s") % s)
        del _db_content['session'][s]

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
            LOG.debug(_("Session is faulty"))
            raise error_util.VimFaultException(
                               [error_util.FAULT_NOT_AUTHENTICATED],
                               _("Session Invalid"))

    def _create_vm(self, method, *args, **kwargs):
        """Creates and registers a VM object with the Host System."""
        config_spec = kwargs.get("config")
        ds = _db_content["Datastore"][_db_content["Datastore"].keys()[0]]
        vm_dict = {"name": config_spec.name,
                  "ds": ds,
                  "powerstate": "poweredOff",
                  "vmPathName": config_spec.files.vmPathName,
                  "numCpu": config_spec.numCPUs,
                  "mem": config_spec.memoryMB}
        virtual_machine = VirtualMachine(**vm_dict)
        _create_object("VirtualMachine", virtual_machine)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _reconfig_vm(self, method, *args, **kwargs):
        """Reconfigures a VM and sets the properties supplied."""
        vm_ref = args[0]
        vm_mdo = _get_vm_mdo(vm_ref)
        vm_mdo.reconfig(self.client.factory, kwargs.get("spec"))
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _create_copy_disk(self, method, vmdk_file_path):
        """Creates/copies a vmdk file object in the datastore."""
        # We need to add/create both .vmdk and .-flat.vmdk files
        flat_vmdk_file_path = \
            vmdk_file_path.replace(".vmdk", "-flat.vmdk")
        _add_file(vmdk_file_path)
        _add_file(flat_vmdk_file_path)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _snapshot_vm(self, method):
        """Snapshots a VM. Here we do nothing for faking sake."""
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _delete_disk(self, method, *args, **kwargs):
        """Deletes .vmdk and -flat.vmdk files corresponding to the VM."""
        vmdk_file_path = kwargs.get("name")
        flat_vmdk_file_path = \
            vmdk_file_path.replace(".vmdk", "-flat.vmdk")
        _remove_file(vmdk_file_path)
        _remove_file(flat_vmdk_file_path)
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

    def _unregister_vm(self, method, *args, **kwargs):
        """Unregisters a VM from the Host System."""
        vm_ref = args[0]
        _get_vm_mdo(vm_ref)
        del _db_content["VirtualMachine"][vm_ref]

    def _search_ds(self, method, *args, **kwargs):
        """Searches the datastore for a file."""
        ds_path = kwargs.get("datastorePath")
        if _db_content.get("files", None) is None:
            raise exception.NoFilesFound()
        for file in _db_content.get("files"):
            if file.find(ds_path) != -1:
                task_mdo = create_task(method, "success")
                return task_mdo.obj
        task_mdo = create_task(method, "error")
        return task_mdo.obj

    def _make_dir(self, method, *args, **kwargs):
        """Creates a directory in the datastore."""
        ds_path = kwargs.get("name")
        if _db_content.get("files", None) is None:
            raise exception.NoFilesFound()
        _db_content["files"].append(ds_path)

    def _set_power_state(self, method, vm_ref, pwr_state="poweredOn"):
        """Sets power state for the VM."""
        if _db_content.get("VirtualMachine", None) is None:
            raise exception.NotFound(_(" No Virtual Machine has been "
                                       "registered yet"))
        if vm_ref not in _db_content.get("VirtualMachine"):
            raise exception.NotFound(_("Virtual Machine with ref %s is not "
                                       "there") % vm_ref)
        vm_mdo = _db_content.get("VirtualMachine").get(vm_ref)
        vm_mdo.set("runtime.powerState", pwr_state)
        task_mdo = create_task(method, "success")
        return task_mdo.obj

    def _retrieve_properties(self, method, *args, **kwargs):
        """Retrieves properties based on the type."""
        spec_set = kwargs.get("specSet")[0]
        type = spec_set.propSet[0].type
        properties = spec_set.propSet[0].pathSet
        objs = spec_set.objectSet
        lst_ret_objs = []
        for obj in objs:
            try:
                obj_ref = obj.obj
                # This means that we are doing a search for the managed
                # dataobjects of the type in the inventory
                if obj_ref == "RootFolder":
                    for mdo_ref in _db_content[type]:
                        mdo = _db_content[type][mdo_ref]
                        # Create a temp Managed object which has the same ref
                        # as the parent object and copies just the properties
                        # asked for. We need .obj along with the propSet of
                        # just the properties asked for
                        temp_mdo = ManagedObject(mdo.objName, mdo.obj)
                        for prop in properties:
                            temp_mdo.set(prop, mdo.get(prop))
                        lst_ret_objs.append(temp_mdo)
                else:
                    if obj_ref in _db_content[type]:
                        mdo = _db_content[type][obj_ref]
                        temp_mdo = ManagedObject(mdo.objName, obj_ref)
                        for prop in properties:
                            temp_mdo.set(prop, mdo.get(prop))
                        lst_ret_objs.append(temp_mdo)
            except Exception, exc:
                LOG.exception(exc)
                continue
        return lst_ret_objs

    def _add_port_group(self, method, *args, **kwargs):
        """Adds a port group to the host system."""
        host_mdo = \
            _db_content["HostSystem"][_db_content["HostSystem"].keys()[0]]
        host_mdo._add_port_group(kwargs.get("portgrp"))

    def __getattr__(self, attr_name):
        if attr_name != "Login":
            self._check_session()
        if attr_name == "Login":
            return lambda *args, **kwargs: self._login()
        elif attr_name == "Logout":
            self._logout()
        elif attr_name == "TerminateSession":
            return lambda *args, **kwargs: self._terminate_session(
                                               *args, **kwargs)
        elif attr_name == "CreateVM_Task":
            return lambda *args, **kwargs: self._create_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "ReconfigVM_Task":
            return lambda *args, **kwargs: self._reconfig_vm(attr_name,
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
        elif attr_name == "CopyVirtualDisk_Task":
            return lambda *args, **kwargs: self._create_copy_disk(attr_name,
                                                kwargs.get("destName"))
        elif attr_name == "DeleteVirtualDisk_Task":
            return lambda *args, **kwargs: self._delete_disk(attr_name,
                                                *args, **kwargs)
        elif attr_name == "UnregisterVM":
            return lambda *args, **kwargs: self._unregister_vm(attr_name,
                                                *args, **kwargs)
        elif attr_name == "SearchDatastore_Task":
            return lambda *args, **kwargs: self._search_ds(attr_name,
                                                *args, **kwargs)
        elif attr_name == "MakeDirectory":
            return lambda *args, **kwargs: self._make_dir(attr_name,
                                                *args, **kwargs)
        elif attr_name == "RetrieveProperties":
            return lambda *args, **kwargs: self._retrieve_properties(
                                                attr_name, *args, **kwargs)
        elif attr_name == "AcquireCloneTicket":
            return lambda *args, **kwargs: self._just_return()
        elif attr_name == "AddPortGroup":
            return lambda *args, **kwargs: self._add_port_group(attr_name,
                                                *args, **kwargs)
