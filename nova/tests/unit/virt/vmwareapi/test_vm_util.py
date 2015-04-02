# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 Canonical Corp.
# All Rights Reserved.
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

import collections
import contextlib

import mock
from oslo_utils import uuidutils
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import pbm

from nova import exception
from nova.network import model as network_model
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.vmwareapi import fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import vm_util


class partialObject(object):
    def __init__(self, path='fake-path'):
        self.path = path
        self.fault = fake.DataObject()


class VMwareVMUtilTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMUtilTestCase, self).setUp()
        fake.reset()
        stubs.set_stubs(self.stubs)
        vm_util.vm_refs_cache_reset()
        self._instance = fake_instance.fake_instance_obj(
            None,
            **{'id': 7, 'name': 'fake!',
               'uuid': uuidutils.generate_uuid(),
               'vcpus': 2, 'memory_mb': 2048})

    def _test_get_stats_from_cluster(self, connection_state="connected",
                                     maintenance_mode=False):
        ManagedObjectRefs = [fake.ManagedObjectReference("host1",
                                                         "HostSystem"),
                             fake.ManagedObjectReference("host2",
                                                         "HostSystem")]
        hosts = fake._convert_to_array_of_mor(ManagedObjectRefs)
        respool = fake.ManagedObjectReference("resgroup-11", "ResourcePool")
        prop_dict = {'host': hosts, 'resourcePool': respool}

        hardware = fake.DataObject()
        hardware.numCpuCores = 8
        hardware.numCpuThreads = 16
        hardware.vendor = "Intel"
        hardware.cpuModel = "Intel(R) Xeon(R)"

        runtime_host_1 = fake.DataObject()
        runtime_host_1.connectionState = "connected"
        runtime_host_1.inMaintenanceMode = False

        runtime_host_2 = fake.DataObject()
        runtime_host_2.connectionState = connection_state
        runtime_host_2.inMaintenanceMode = maintenance_mode

        prop_list_host_1 = [fake.Prop(name="hardware_summary", val=hardware),
                            fake.Prop(name="runtime_summary",
                                      val=runtime_host_1)]
        prop_list_host_2 = [fake.Prop(name="hardware_summary", val=hardware),
                            fake.Prop(name="runtime_summary",
                                      val=runtime_host_2)]

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.ObjectContent("prop_list_host1",
                                                   prop_list_host_1))
        fake_objects.add_object(fake.ObjectContent("prop_list_host1",
                                                   prop_list_host_2))

        respool_resource_usage = fake.DataObject()
        respool_resource_usage.maxUsage = 5368709120
        respool_resource_usage.overallUsage = 2147483648

        def fake_call_method(*args):
            if "get_dynamic_properties" in args:
                return prop_dict
            elif "get_properties_for_a_collection_of_objects" in args:
                return fake_objects
            else:
                return respool_resource_usage

        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method', fake_call_method):
            result = vm_util.get_stats_from_cluster(session, "cluster1")
            mem_info = {}
            if connection_state == "connected" and not maintenance_mode:
                vcpus = 32
            else:
                vcpus = 16
            mem_info['total'] = 5120
            mem_info['free'] = 3072
            expected_stats = {'vcpus': vcpus, 'mem': mem_info}
            self.assertEqual(expected_stats, result)

    def test_get_stats_from_cluster_hosts_connected_and_active(self):
        self._test_get_stats_from_cluster()

    def test_get_stats_from_cluster_hosts_disconnected_and_active(self):
        self._test_get_stats_from_cluster(connection_state="disconnected")

    def test_get_stats_from_cluster_hosts_connected_and_maintenance(self):
        self._test_get_stats_from_cluster(maintenance_mode=True)

    def test_get_host_ref_no_hosts_in_cluster(self):
        self.assertRaises(exception.NoValidHost,
                          vm_util.get_host_ref,
                          fake.FakeObjectRetrievalSession(""), 'fake_cluster')

    def test_get_resize_spec(self):
        vcpus = 2
        memory_mb = 2048
        extra_specs = vm_util.ExtraSpecs()
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_resize_spec(fake_factory,
                                            vcpus, memory_mb, extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.memoryMB = memory_mb
        expected.numCPUs = vcpus
        cpuAllocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpuAllocation.reservation = 0
        cpuAllocation.limit = -1
        cpuAllocation.shares = fake_factory.create('ns0:SharesInfo')
        cpuAllocation.shares.level = 'normal'
        cpuAllocation.shares.shares = 0
        expected.cpuAllocation = cpuAllocation

        self.assertEqual(expected, result)

    def test_get_resize_spec_with_limits(self):
        vcpus = 2
        memory_mb = 2048
        cpu_limits = vm_util.CpuLimits(cpu_limit=7,
                                       cpu_reservation=6)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_resize_spec(fake_factory,
                                            vcpus, memory_mb, extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.memoryMB = memory_mb
        expected.numCPUs = vcpus
        cpuAllocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpuAllocation.reservation = 6
        cpuAllocation.limit = 7
        cpuAllocation.shares = fake_factory.create('ns0:SharesInfo')
        cpuAllocation.shares.level = 'normal'
        cpuAllocation.shares.shares = 0
        expected.cpuAllocation = cpuAllocation

        self.assertEqual(expected, result)

    def test_get_cdrom_attach_config_spec(self):
        fake_factory = fake.FakeFactory()
        datastore = fake.Datastore()
        result = vm_util.get_cdrom_attach_config_spec(fake_factory,
                                             datastore,
                                             "/tmp/foo.iso",
                                             200, 0)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.deviceChange = []
        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.operation = 'add'

        device_change.device = fake_factory.create('ns0:VirtualCdrom')
        device_change.device.controllerKey = 200
        device_change.device.unitNumber = 0
        device_change.device.key = -1

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = False
        connectable.startConnected = True
        connectable.connected = True
        device_change.device.connectable = connectable

        backing = fake_factory.create('ns0:VirtualCdromIsoBackingInfo')
        backing.fileName = '/tmp/foo.iso'
        backing.datastore = datastore
        device_change.device.backing = backing
        expected.deviceChange.append(device_change)
        self.assertEqual(expected, result)

    def test_lsilogic_controller_spec(self):
        # Test controller spec returned for lsiLogic sas adapter type
        config_spec = vm_util.create_controller_spec(fake.FakeFactory(), -101,
                          adapter_type="lsiLogicsas")
        self.assertEqual("ns0:VirtualLsiLogicSASController",
                         config_spec.device.obj_name)

    def test_paravirtual_controller_spec(self):
        # Test controller spec returned for paraVirtual adapter type
        config_spec = vm_util.create_controller_spec(fake.FakeFactory(), -101,
                          adapter_type="paraVirtual")
        self.assertEqual("ns0:ParaVirtualSCSIController",
                         config_spec.device.obj_name)

    def _vmdk_path_and_adapter_type_devices(self, filename, parent=None):
        # Test the adapter_type returned for a lsiLogic sas controller
        controller_key = 1000
        disk = fake.VirtualDisk()
        disk.controllerKey = controller_key
        disk_backing = fake.VirtualDiskFlatVer2BackingInfo()
        disk_backing.fileName = filename
        disk.capacityInBytes = 1024
        if parent:
            disk_backing.parent = parent
        disk.backing = disk_backing
        # Ephemeral disk
        e_disk = fake.VirtualDisk()
        e_disk.controllerKey = controller_key
        disk_backing = fake.VirtualDiskFlatVer2BackingInfo()
        disk_backing.fileName = '[test_datastore] uuid/ephemeral_0.vmdk'
        e_disk.capacityInBytes = 512
        e_disk.backing = disk_backing
        controller = fake.VirtualLsiLogicSASController()
        controller.key = controller_key
        devices = [disk, e_disk, controller]
        return devices

    def test_get_vmdk_path_and_adapter_type(self):
        filename = '[test_datastore] uuid/uuid.vmdk'
        devices = self._vmdk_path_and_adapter_type_devices(filename)
        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method', return_value=devices):
            vmdk = vm_util.get_vmdk_info(session, None)
            self.assertEqual('lsiLogicsas', vmdk.adapter_type)
            self.assertEqual('[test_datastore] uuid/ephemeral_0.vmdk',
                             vmdk.path)
            self.assertEqual(512, vmdk.capacity_in_bytes)
            self.assertEqual(devices[1], vmdk.device)

    def test_get_vmdk_path_and_adapter_type_with_match(self):
        n_filename = '[test_datastore] uuid/uuid.vmdk'
        devices = self._vmdk_path_and_adapter_type_devices(n_filename)
        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method', return_value=devices):
            vmdk = vm_util.get_vmdk_info(session, None, uuid='uuid')
            self.assertEqual('lsiLogicsas', vmdk.adapter_type)
            self.assertEqual(n_filename, vmdk.path)
            self.assertEqual(1024, vmdk.capacity_in_bytes)
            self.assertEqual(devices[0], vmdk.device)

    def test_get_vmdk_path_and_adapter_type_with_nomatch(self):
        n_filename = '[test_datastore] diuu/diuu.vmdk'
        session = fake.FakeSession()
        devices = self._vmdk_path_and_adapter_type_devices(n_filename)
        with mock.patch.object(session, '_call_method', return_value=devices):
            vmdk = vm_util.get_vmdk_info(session, None, uuid='uuid')
            self.assertIsNone(vmdk.adapter_type)
            self.assertIsNone(vmdk.path)
            self.assertEqual(0, vmdk.capacity_in_bytes)
            self.assertIsNone(vmdk.device)

    def test_get_vmdk_adapter_type(self):
        # Test for the adapter_type to be used in vmdk descriptor
        # Adapter type in vmdk descriptor is same for LSI-SAS, LSILogic
        # and ParaVirtual
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("lsiLogic")
        self.assertEqual("lsiLogic", vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("lsiLogicsas")
        self.assertEqual("lsiLogic", vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("paraVirtual")
        self.assertEqual("lsiLogic", vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("dummyAdapter")
        self.assertEqual("dummyAdapter", vmdk_adapter_type)

    def test_get_scsi_adapter_type(self):
        vm = fake.VirtualMachine()
        devices = vm.get("config.hardware.device").VirtualDevice
        scsi_controller = fake.VirtualLsiLogicController()
        ide_controller = fake.VirtualIDEController()
        devices.append(scsi_controller)
        devices.append(ide_controller)
        fake._update_object("VirtualMachine", vm)
        # return the scsi type, not ide
        hardware_device = vm.get("config.hardware.device")
        self.assertEqual(constants.DEFAULT_ADAPTER_TYPE,
                         vm_util.get_scsi_adapter_type(hardware_device))

    def test_get_scsi_adapter_type_with_error(self):
        vm = fake.VirtualMachine()
        devices = vm.get("config.hardware.device").VirtualDevice
        scsi_controller = fake.VirtualLsiLogicController()
        ide_controller = fake.VirtualIDEController()
        devices.append(scsi_controller)
        devices.append(ide_controller)
        fake._update_object("VirtualMachine", vm)
        # the controller is not suitable since the device under this controller
        # has exceeded SCSI_MAX_CONNECT_NUMBER
        for i in range(0, constants.SCSI_MAX_CONNECT_NUMBER):
            scsi_controller.device.append('device' + str(i))
        hardware_device = vm.get("config.hardware.device")
        self.assertRaises(exception.StorageError,
                          vm_util.get_scsi_adapter_type,
                          hardware_device)

    def test_find_allocated_slots(self):
        disk1 = fake.VirtualDisk(200, 0)
        disk2 = fake.VirtualDisk(200, 1)
        disk3 = fake.VirtualDisk(201, 1)
        ide0 = fake.VirtualIDEController(200)
        ide1 = fake.VirtualIDEController(201)
        scsi0 = fake.VirtualLsiLogicController(key=1000, scsiCtlrUnitNumber=7)
        devices = [disk1, disk2, disk3, ide0, ide1, scsi0]
        taken = vm_util._find_allocated_slots(devices)
        self.assertEqual([0, 1], sorted(taken[200]))
        self.assertEqual([1], taken[201])
        self.assertEqual([7], taken[1000])

    def test_allocate_controller_key_and_unit_number_ide_default(self):
        # Test that default IDE controllers are used when there is a free slot
        # on them
        disk1 = fake.VirtualDisk(200, 0)
        disk2 = fake.VirtualDisk(200, 1)
        ide0 = fake.VirtualIDEController(200)
        ide1 = fake.VirtualIDEController(201)
        devices = [disk1, disk2, ide0, ide1]
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                            None,
                                                            devices,
                                                            'ide')
        self.assertEqual(201, controller_key)
        self.assertEqual(0, unit_number)
        self.assertIsNone(controller_spec)

    def test_allocate_controller_key_and_unit_number_ide(self):
        # Test that a new controller is created when there is no free slot on
        # the default IDE controllers
        ide0 = fake.VirtualIDEController(200)
        ide1 = fake.VirtualIDEController(201)
        devices = [ide0, ide1]
        for controller_key in [200, 201]:
            for unit_number in [0, 1]:
                disk = fake.VirtualDisk(controller_key, unit_number)
                devices.append(disk)
        factory = fake.FakeFactory()
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                            factory,
                                                            devices,
                                                            'ide')
        self.assertEqual(-101, controller_key)
        self.assertEqual(0, unit_number)
        self.assertIsNotNone(controller_spec)

    def test_allocate_controller_key_and_unit_number_scsi(self):
        # Test that we allocate on existing SCSI controller if there is a free
        # slot on it
        devices = [fake.VirtualLsiLogicController(1000, scsiCtlrUnitNumber=7)]
        for unit_number in range(7):
            disk = fake.VirtualDisk(1000, unit_number)
            devices.append(disk)
        factory = fake.FakeFactory()
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                            factory,
                                                            devices,
                                                            'lsiLogic')
        self.assertEqual(1000, controller_key)
        self.assertEqual(8, unit_number)
        self.assertIsNone(controller_spec)

    def test_get_vnc_config_spec(self):
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vnc_config_spec(fake_factory,
                                             7)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.extraConfig = []

        remote_display_vnc_enabled = fake_factory.create('ns0:OptionValue')
        remote_display_vnc_enabled.value = 'true'
        remote_display_vnc_enabled.key = 'RemoteDisplay.vnc.enabled'
        expected.extraConfig.append(remote_display_vnc_enabled)

        remote_display_vnc_port = fake_factory.create('ns0:OptionValue')
        remote_display_vnc_port.value = 7
        remote_display_vnc_port.key = 'RemoteDisplay.vnc.port'
        expected.extraConfig.append(remote_display_vnc_port)

        self.assertEqual(expected, result)

    def _create_fake_vms(self):
        fake_vms = fake.FakeRetrieveResult()
        OptionValue = collections.namedtuple('OptionValue', ['key', 'value'])
        for i in range(10):
            vm = fake.ManagedObject()
            opt_val = OptionValue(key='', value=5900 + i)
            vm.set(vm_util.VNC_CONFIG_KEY, opt_val)
            fake_vms.add_object(vm)
        return fake_vms

    def test_get_vnc_port(self):
        fake_vms = self._create_fake_vms()
        self.flags(vnc_port=5900, group='vmware')
        self.flags(vnc_port_total=10000, group='vmware')
        actual = vm_util.get_vnc_port(
            fake.FakeObjectRetrievalSession(fake_vms))
        self.assertEqual(actual, 5910)

    def test_get_vnc_port_exhausted(self):
        fake_vms = self._create_fake_vms()
        self.flags(vnc_port=5900, group='vmware')
        self.flags(vnc_port_total=10, group='vmware')
        self.assertRaises(exception.ConsolePortRangeExhausted,
                          vm_util.get_vnc_port,
                          fake.FakeObjectRetrievalSession(fake_vms))

    def test_get_all_cluster_refs_by_name_none(self):
        fake_objects = fake.FakeRetrieveResult()
        refs = vm_util.get_all_cluster_refs_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), ['fake_cluster'])
        self.assertEqual({}, refs)

    def test_get_all_cluster_refs_by_name_exists(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.ClusterComputeResource(name='cluster'))
        refs = vm_util.get_all_cluster_refs_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), ['cluster'])
        self.assertEqual(1, len(refs))

    def test_get_all_cluster_refs_by_name_missing(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(partialObject(path='cluster'))
        refs = vm_util.get_all_cluster_refs_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), ['cluster'])
        self.assertEqual({}, refs)

    def test_propset_dict_simple(self):
        ObjectContent = collections.namedtuple('ObjectContent', ['propSet'])
        DynamicProperty = collections.namedtuple('Property', ['name', 'val'])

        object = ObjectContent(propSet=[
                    DynamicProperty(name='foo', val="bar")])
        propdict = vm_util.propset_dict(object.propSet)
        self.assertEqual("bar", propdict['foo'])

    def test_propset_dict_complex(self):
        ObjectContent = collections.namedtuple('ObjectContent', ['propSet'])
        DynamicProperty = collections.namedtuple('Property', ['name', 'val'])
        MoRef = collections.namedtuple('Val', ['value'])

        object = ObjectContent(propSet=[
                    DynamicProperty(name='foo', val="bar"),
                    DynamicProperty(name='some.thing',
                                    val=MoRef(value='else')),
                    DynamicProperty(name='another.thing', val='value')])

        propdict = vm_util.propset_dict(object.propSet)
        self.assertEqual("bar", propdict['foo'])
        self.assertTrue(hasattr(propdict['some.thing'], 'value'))
        self.assertEqual("else", propdict['some.thing'].value)
        self.assertEqual("value", propdict['another.thing'])

    def _test_detach_virtual_disk_spec(self, destroy_disk=False):
        virtual_device_config = vm_util.detach_virtual_disk_spec(
                                                     fake.FakeFactory(),
                                                     'fake_device',
                                                     destroy_disk)
        self.assertEqual('remove', virtual_device_config.operation)
        self.assertEqual('fake_device', virtual_device_config.device)
        self.assertEqual('ns0:VirtualDeviceConfigSpec',
                         virtual_device_config.obj_name)
        if destroy_disk:
            self.assertEqual('destroy', virtual_device_config.fileOperation)
        else:
            self.assertFalse(hasattr(virtual_device_config, 'fileOperation'))

    def test_detach_virtual_disk_spec(self):
        self._test_detach_virtual_disk_spec(destroy_disk=False)

    def test_detach_virtual_disk_destroy_spec(self):
        self._test_detach_virtual_disk_spec(destroy_disk=True)

    def test_get_vm_create_spec(self):
        extra_specs = vm_util.ExtraSpecs()
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)

        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.name = self._instance.uuid
        expected.instanceUuid = self._instance.uuid
        expected.deviceChange = []
        expected.numCPUs = 2

        expected.version = None
        expected.memoryMB = 2048
        expected.guestId = 'otherGuest'
        expected.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)
        expected.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        expected.files.vmPathName = '[fake-datastore]'

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        expected.tools = fake_factory.create('ns0:ToolsConfigInfo')
        expected.tools.afterPowerOn = True
        expected.tools.afterResume = True
        expected.tools.beforeGuestReboot = True
        expected.tools.beforeGuestShutdown = True
        expected.tools.beforeGuestStandby = True

        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_allocations(self):
        cpu_limits = vm_util.CpuLimits(cpu_limit=7,
                                       cpu_reservation=6)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.deviceChange = []
        expected.guestId = 'otherGuest'
        expected.instanceUuid = self._instance.uuid
        expected.memoryMB = self._instance.memory_mb
        expected.name = self._instance.uuid
        expected.numCPUs = self._instance.vcpus
        expected.version = None

        expected.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        expected.files.vmPathName = '[fake-datastore]'

        expected.tools = fake_factory.create('ns0:ToolsConfigInfo')
        expected.tools.afterPowerOn = True
        expected.tools.afterResume = True
        expected.tools.beforeGuestReboot = True
        expected.tools.beforeGuestShutdown = True
        expected.tools.beforeGuestStandby = True

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        cpu_allocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpu_allocation.limit = 7
        cpu_allocation.reservation = 6
        cpu_allocation.shares = fake_factory.create('ns0:SharesInfo')
        cpu_allocation.shares.level = 'normal'
        cpu_allocation.shares.shares = 0
        expected.cpuAllocation = cpu_allocation

        expected.extraConfig = []
        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.key = 'nvp.vm-uuid'
        extra_config.value = self._instance.uuid
        expected.extraConfig.append(extra_config)
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_limit(self):
        cpu_limits = vm_util.CpuLimits(cpu_limit=7)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        expected.files.vmPathName = '[fake-datastore]'
        expected.instanceUuid = self._instance.uuid
        expected.name = self._instance.uuid
        expected.deviceChange = []
        expected.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        expected.version = None
        expected.guestId = 'otherGuest'

        expected.tools = fake_factory.create('ns0:ToolsConfigInfo')
        expected.tools.afterPowerOn = True
        expected.tools.afterResume = True
        expected.tools.beforeGuestReboot = True
        expected.tools.beforeGuestShutdown = True
        expected.tools.beforeGuestStandby = True

        cpu_allocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpu_allocation.limit = 7
        cpu_allocation.reservation = 0
        cpu_allocation.shares = fake_factory.create('ns0:SharesInfo')
        cpu_allocation.shares.level = 'normal'
        cpu_allocation.shares.shares = 0
        expected.cpuAllocation = cpu_allocation

        expected.numCPUs = 2
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_share(self):
        cpu_limits = vm_util.CpuLimits(cpu_shares_level='high')
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')

        expected.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        expected.files.vmPathName = '[fake-datastore]'

        expected.instanceUuid = self._instance.uuid
        expected.name = self._instance.uuid
        expected.deviceChange = []

        expected.extraConfig = []
        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.type = 'instance'
        expected.managedBy.extensionKey = 'org.openstack.compute'

        expected.version = None
        expected.guestId = 'otherGuest'

        expected.tools = fake_factory.create('ns0:ToolsConfigInfo')
        expected.tools.beforeGuestStandby = True
        expected.tools.beforeGuestReboot = True
        expected.tools.beforeGuestShutdown = True
        expected.tools.afterResume = True
        expected.tools.afterPowerOn = True

        cpu_allocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpu_allocation.reservation = 0
        cpu_allocation.limit = -1
        cpu_allocation.shares = fake_factory.create('ns0:SharesInfo')
        cpu_allocation.shares.level = 'high'
        cpu_allocation.shares.shares = 0
        expected.cpuAllocation = cpu_allocation
        expected.numCPUs = 2
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_share_custom(self):
        cpu_limits = vm_util.CpuLimits(cpu_shares_level='custom',
                                       cpu_shares_share=1948)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        expected.files.vmPathName = '[fake-datastore]'

        expected.instanceUuid = self._instance.uuid
        expected.name = self._instance.uuid
        expected.deviceChange = []

        expected.extraConfig = []
        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.key = 'nvp.vm-uuid'
        extra_config.value = self._instance.uuid
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048
        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        expected.version = None
        expected.guestId = 'otherGuest'
        expected.tools = fake_factory.create('ns0:ToolsConfigInfo')
        expected.tools.beforeGuestStandby = True
        expected.tools.beforeGuestReboot = True
        expected.tools.beforeGuestShutdown = True
        expected.tools.afterResume = True
        expected.tools.afterPowerOn = True

        cpu_allocation = fake_factory.create('ns0:ResourceAllocationInfo')
        cpu_allocation.reservation = 0
        cpu_allocation.limit = -1
        cpu_allocation.shares = fake_factory.create('ns0:SharesInfo')
        cpu_allocation.shares.level = 'custom'
        cpu_allocation.shares.shares = 1948
        expected.cpuAllocation = cpu_allocation
        expected.numCPUs = 2
        self.assertEqual(expected, result)

    def test_create_vm(self):

        method_list = ['CreateVM_Task', 'get_dynamic_property']

        def fake_call_method(module, method, *args, **kwargs):
            expected_method = method_list.pop(0)
            self.assertEqual(expected_method, method)
            if (expected_method == 'CreateVM_Task'):
                return 'fake_create_vm_task'
            elif (expected_method == 'get_dynamic_property'):
                task_info = mock.Mock(state="success", result="fake_vm_ref")
                return task_info
            else:
                self.fail('Should not get here....')

        def fake_wait_for_task(self, *args):
            task_info = mock.Mock(state="success", result="fake_vm_ref")
            return task_info

        session = fake.FakeSession()
        fake_call_mock = mock.Mock(side_effect=fake_call_method)
        fake_wait_mock = mock.Mock(side_effect=fake_wait_for_task)
        with contextlib.nested(
                mock.patch.object(session, '_wait_for_task',
                                  fake_wait_mock),
                mock.patch.object(session, '_call_method',
                                  fake_call_mock)
        ) as (wait_for_task, call_method):
            vm_ref = vm_util.create_vm(
                session,
                self._instance,
                'fake_vm_folder',
                'fake_config_spec',
                'fake_res_pool_ref')
            self.assertEqual('fake_vm_ref', vm_ref)

            call_method.assert_called_once_with(mock.ANY, 'CreateVM_Task',
                'fake_vm_folder', config='fake_config_spec',
                pool='fake_res_pool_ref')
            wait_for_task.assert_called_once_with('fake_create_vm_task')

    @mock.patch.object(vm_util.LOG, 'warning')
    def test_create_vm_invalid_guestid(self, mock_log_warn):
        """Ensure we warn when create_vm() fails after we passed an
        unrecognised guestId
        """

        found = [False]

        def fake_log_warn(msg, values):
            if not isinstance(values, dict):
                return
            if values.get('ostype') == 'invalid_os_type':
                found[0] = True
        mock_log_warn.side_effect = fake_log_warn

        session = driver.VMwareAPISession()

        config_spec = vm_util.get_vm_create_spec(
            session.vim.client.factory,
            self._instance, 'fake-datastore', [],
            vm_util.ExtraSpecs(),
            os_type='invalid_os_type')

        self.assertRaises(vexc.VMwareDriverException,
                          vm_util.create_vm, session, self._instance,
                          'folder', config_spec, 'res-pool')
        self.assertTrue(found[0])

    def test_convert_vif_model(self):
        expected = "VirtualE1000"
        result = vm_util.convert_vif_model(network_model.VIF_MODEL_E1000)
        self.assertEqual(expected, result)
        expected = "VirtualE1000e"
        result = vm_util.convert_vif_model(network_model.VIF_MODEL_E1000E)
        self.assertEqual(expected, result)
        types = ["VirtualE1000", "VirtualE1000e", "VirtualPCNet32",
                 "VirtualVmxnet"]
        for type in types:
            self.assertEqual(type,
                             vm_util.convert_vif_model(type))
        self.assertRaises(exception.Invalid,
                          vm_util.convert_vif_model,
                          "InvalidVifModel")

    def test_power_on_instance_with_vm_ref(self):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(session, "_wait_for_task"),
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.power_on_instance(session, self._instance,
                                      vm_ref='fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOnVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def test_power_on_instance_without_vm_ref(self):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(vm_util, "get_vm_ref",
                              return_value='fake-vm-ref'),
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(session, "_wait_for_task"),
        ) as (fake_get_vm_ref, fake_call_method, fake_wait_for_task):
            vm_util.power_on_instance(session, self._instance)
            fake_get_vm_ref.assert_called_once_with(session, self._instance)
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOnVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def test_power_on_instance_with_exception(self):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(session, "_wait_for_task",
                              side_effect=exception.NovaException('fake')),
        ) as (fake_call_method, fake_wait_for_task):
            self.assertRaises(exception.NovaException,
                              vm_util.power_on_instance,
                              session, self._instance,
                              vm_ref='fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOnVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def test_power_on_instance_with_power_state_exception(self):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(
                    session, "_wait_for_task",
                    side_effect=vexc.InvalidPowerStateException),
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.power_on_instance(session, self._instance,
                                      vm_ref='fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOnVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def test_create_virtual_disk(self):
        session = fake.FakeSession()
        dm = session.vim.service_content.virtualDiskManager
        with contextlib.nested(
            mock.patch.object(vm_util, "get_vmdk_create_spec",
                              return_value='fake-spec'),
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(session, "_wait_for_task"),
        ) as (fake_get_spec, fake_call_method, fake_wait_for_task):
            vm_util.create_virtual_disk(session, 'fake-dc-ref',
                                        'fake-adapter-type', 'fake-disk-type',
                                        'fake-path', 7)
            fake_get_spec.assert_called_once_with(
                    session.vim.client.factory, 7,
                    'fake-adapter-type',
                    'fake-disk-type')
            fake_call_method.assert_called_once_with(
                    session.vim,
                    "CreateVirtualDisk_Task",
                    dm,
                    name='fake-path',
                    datacenter='fake-dc-ref',
                    spec='fake-spec')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def test_copy_virtual_disk(self):
        session = fake.FakeSession()
        dm = session.vim.service_content.virtualDiskManager
        with contextlib.nested(
            mock.patch.object(session, "_call_method",
                              return_value='fake-task'),
            mock.patch.object(session, "_wait_for_task"),
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.copy_virtual_disk(session, 'fake-dc-ref',
                                      'fake-source', 'fake-dest')
            fake_call_method.assert_called_once_with(
                    session.vim,
                    "CopyVirtualDisk_Task",
                    dm,
                    sourceName='fake-source',
                    sourceDatacenter='fake-dc-ref',
                    destName='fake-dest')
            fake_wait_for_task.assert_called_once_with('fake-task')

    def _create_fake_vm_objects(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.VirtualMachine())
        return fake_objects

    def test_get_values(self):
        objects = self._create_fake_vm_objects()
        query = vm_util.get_values_from_object_properties(
            fake.FakeObjectRetrievalSession(objects), objects)
        self.assertEqual('poweredOn', query['runtime.powerState'])
        self.assertEqual('guestToolsRunning',
                         query['summary.guest.toolsRunningStatus'])
        self.assertEqual('toolsOk', query['summary.guest.toolsStatus'])

    def test_reconfigure_vm(self):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake_reconfigure_task'),
            mock.patch.object(session, '_wait_for_task')
        ) as (_call_method, _wait_for_task):
            vm_util.reconfigure_vm(session, 'fake-ref', 'fake-spec')
            _call_method.assert_called_once_with(mock.ANY,
                'ReconfigVM_Task', 'fake-ref', spec='fake-spec')
            _wait_for_task.assert_called_once_with(
                'fake_reconfigure_task')

    def test_get_network_attach_config_spec_opaque(self):
        vif_info = {'network_name': 'br-int',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'OpaqueNetwork',
                            'network-id': 'fake-network-id',
                            'network-type': 'opaque'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        fake_factory = fake.FakeFactory()
        result = vm_util.get_network_attach_config_spec(
                fake_factory, vif_info, 1)
        card = 'ns0:VirtualEthernetCardOpaqueNetworkBackingInfo'
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.extraConfig = []

        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.value = vif_info['iface_id']
        extra_config.key = 'nvp.iface-id.1'
        expected.extraConfig.append(extra_config)

        expected.deviceChange = []
        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.operation = 'add'

        device = fake_factory.create('ns0:VirtualE1000')
        device.macAddress = vif_info['mac_address']
        device.addressType = 'manual'
        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.startConnected = True
        connectable.connected = True
        device.connectable = connectable
        backing = fake_factory.create(card)
        backing.opaqueNetworkType = vif_info['network_ref']['network-type']
        backing.opaqueNetworkId = vif_info['network_ref']['network-id']
        device.backing = backing
        device.key = -47
        device.wakeOnLanEnabled = True
        device_change.device = device
        expected.deviceChange.append(device_change)

        self.assertEqual(expected, result)

    def test_get_network_attach_config_spec_dvs(self):
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        fake_factory = fake.FakeFactory()
        result = vm_util.get_network_attach_config_spec(
                fake_factory, vif_info, 1)
        port = 'ns0:DistributedVirtualSwitchPortConnection'
        backing = 'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo'

        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.extraConfig = []

        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.value = vif_info['iface_id']
        extra_config.key = 'nvp.iface-id.1'
        expected.extraConfig.append(extra_config)

        expected.deviceChange = []

        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.operation = 'add'

        device = fake_factory.create('ns0:VirtualE1000')
        device.macAddress = vif_info['mac_address']
        device.key = -47
        device.addressType = 'manual'
        device.wakeOnLanEnabled = True

        device.backing = fake_factory.create(backing)
        device.backing.port = fake_factory.create(port)
        device.backing.port.portgroupKey = vif_info['network_ref']['dvpg']
        device.backing.port.switchUuid = vif_info['network_ref']['dvsw']

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.connected = True
        connectable.startConnected = True
        device.connectable = connectable
        device_change.device = device

        expected.deviceChange.append(device_change)
        self.assertEqual(expected, result)

    def test_get_network_detach_config_spec(self):
        fake_factory = fake.FakeFactory()
        result = vm_util.get_network_detach_config_spec(
                fake_factory, 'fake-device', 2)

        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.extraConfig = []

        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.value = 'free'
        extra_config.key = 'nvp.iface-id.2'
        expected.extraConfig.append(extra_config)
        expected.deviceChange = []
        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.device = 'fake-device'
        device_change.operation = 'remove'
        expected.deviceChange.append(device_change)

        self.assertEqual(expected, result)

    @mock.patch.object(vm_util, "get_vm_ref")
    def test_power_off_instance(self, fake_get_ref):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake-task'),
            mock.patch.object(session, '_wait_for_task')
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.power_off_instance(session, self._instance, 'fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOffVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')
            self.assertFalse(fake_get_ref.called)

    @mock.patch.object(vm_util, "get_vm_ref", return_value="fake-vm-ref")
    def test_power_off_instance_no_vm_ref(self, fake_get_ref):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake-task'),
            mock.patch.object(session, '_wait_for_task')
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.power_off_instance(session, self._instance)
            fake_get_ref.assert_called_once_with(session, self._instance)
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOffVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')

    @mock.patch.object(vm_util, "get_vm_ref")
    def test_power_off_instance_with_exception(self, fake_get_ref):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake-task'),
            mock.patch.object(session, '_wait_for_task',
                              side_effect=exception.NovaException('fake'))
        ) as (fake_call_method, fake_wait_for_task):
            self.assertRaises(exception.NovaException,
                              vm_util.power_off_instance,
                              session, self._instance, 'fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOffVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')
            self.assertFalse(fake_get_ref.called)

    @mock.patch.object(vm_util, "get_vm_ref")
    def test_power_off_instance_power_state_exception(self, fake_get_ref):
        session = fake.FakeSession()
        with contextlib.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake-task'),
            mock.patch.object(
                    session, '_wait_for_task',
                    side_effect=vexc.InvalidPowerStateException)
        ) as (fake_call_method, fake_wait_for_task):
            vm_util.power_off_instance(session, self._instance, 'fake-vm-ref')
            fake_call_method.assert_called_once_with(session.vim,
                                                     "PowerOffVM_Task",
                                                     'fake-vm-ref')
            fake_wait_for_task.assert_called_once_with('fake-task')
            self.assertFalse(fake_get_ref.called)

    def test_get_vm_create_spec_updated_hw_version(self):
        extra_specs = vm_util.ExtraSpecs(hw_version='vmx-08')
        result = vm_util.get_vm_create_spec(fake.FakeFactory(),
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs=extra_specs)
        self.assertEqual('vmx-08', result.version)

    def test_vm_create_spec_with_profile_spec(self):
        datastore = ds_obj.Datastore('fake-ds-ref', 'fake-ds-name')
        extra_specs = vm_util.ExtraSpecs()
        create_spec = vm_util.get_vm_create_spec(fake.FakeFactory(),
                                            self._instance,
                                            datastore.name, [],
                                            extra_specs,
                                            profile_spec='fake_profile_spec')
        self.assertEqual(['fake_profile_spec'], create_spec.vmProfile)

    @mock.patch.object(pbm, 'get_profile_id_by_name')
    def test_get_storage_profile_spec(self, mock_retrieve_profile_id):
        fake_profile_id = fake.DataObject()
        fake_profile_id.uniqueId = 'fake_unique_id'
        mock_retrieve_profile_id.return_value = fake_profile_id
        profile_spec = vm_util.get_storage_profile_spec(fake.FakeSession(),
                                                        'fake_policy')
        self.assertEqual('ns0:VirtualMachineDefinedProfileSpec',
                         profile_spec.obj_name)
        self.assertEqual(fake_profile_id.uniqueId, profile_spec.profileId)

    @mock.patch.object(pbm, 'get_profile_id_by_name')
    def test_storage_spec_empty_profile(self, mock_retrieve_profile_id):
        mock_retrieve_profile_id.return_value = None
        profile_spec = vm_util.get_storage_profile_spec(fake.FakeSession(),
                                                        'fake_policy')
        self.assertIsNone(profile_spec)

    def test_get_ephemeral_name(self):
        filename = vm_util.get_ephemeral_name(0)
        self.assertEqual('ephemeral_0.vmdk', filename)

    def test_detach_and_delete_devices_config_spec(self):
        fake_devices = ['device1', 'device2']
        fake_factory = fake.FakeFactory()
        result = vm_util._detach_and_delete_devices_config_spec(fake_factory,
                                                                fake_devices)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.deviceChange = []
        device1 = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device1.device = 'device1'
        device1.operation = 'remove'
        device1.fileOperation = 'destroy'
        expected.deviceChange.append(device1)

        device2 = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device2.device = 'device2'
        device2.operation = 'remove'
        device2.fileOperation = 'destroy'
        expected.deviceChange.append(device2)
        self.assertEqual(expected, result)

    @mock.patch.object(vm_util, 'reconfigure_vm')
    def test_detach_devices_from_vm(self, mock_reconfigure):
        fake_devices = ['device1', 'device2']
        session = fake.FakeSession()
        vm_util.detach_devices_from_vm(session,
                                       'fake-ref',
                                       fake_devices)
        mock_reconfigure.assert_called_once_with(session, 'fake-ref', mock.ANY)

    def test_get_vm_boot_spec(self):
        disk = fake.VirtualDisk()
        disk.key = 7
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_boot_spec(fake_factory,
                                          disk)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        boot_disk = fake_factory.create(
            'ns0:VirtualMachineBootOptionsBootableDiskDevice')
        boot_disk.deviceKey = disk.key
        boot_options = fake_factory.create('ns0:VirtualMachineBootOptions')
        boot_options.bootOrder = [boot_disk]
        expected.bootOptions = boot_options
        self.assertEqual(expected, result)

    def _get_devices(self, filename):
        devices = fake._create_array_of_type('VirtualDevice')
        devices.VirtualDevice = self._vmdk_path_and_adapter_type_devices(
            filename)
        return devices

    def test_find_rescue_device(self):
        filename = '[test_datastore] uuid/uuid-rescue.vmdk'
        devices = self._get_devices(filename)
        device = vm_util.find_rescue_device(devices, self._instance)
        self.assertEqual(filename, device.backing.fileName)

    def test_find_rescue_device_not_found(self):
        filename = '[test_datastore] uuid/uuid.vmdk'
        devices = self._get_devices(filename)
        self.assertRaises(exception.NotFound,
                          vm_util.find_rescue_device,
                          devices,
                          self._instance)


@mock.patch.object(driver.VMwareAPISession, 'vim', stubs.fake_vim_prop)
class VMwareVMUtilGetHostRefTestCase(test.NoDBTestCase):
    # N.B. Mocking on the class only mocks test_*(), but we need
    # VMwareAPISession.vim to be mocked in both setUp and tests. Not mocking in
    # setUp causes object initialisation to fail. Not mocking in tests results
    # in vim calls not using FakeVim.
    @mock.patch.object(driver.VMwareAPISession, 'vim', stubs.fake_vim_prop)
    def setUp(self):
        super(VMwareVMUtilGetHostRefTestCase, self).setUp()
        fake.reset()
        vm_util.vm_refs_cache_reset()

        self.session = driver.VMwareAPISession()

        # Create a fake VirtualMachine running on a known host
        self.host_ref = fake._db_content['HostSystem'].keys()[0]
        self.vm_ref = fake.create_vm(host_ref=self.host_ref)

    @mock.patch.object(vm_util, 'get_vm_ref')
    def test_get_host_ref_for_vm(self, mock_get_vm_ref):
        mock_get_vm_ref.return_value = self.vm_ref

        ret = vm_util.get_host_ref_for_vm(self.session, 'fake-instance')

        mock_get_vm_ref.assert_called_once_with(self.session, 'fake-instance')
        self.assertEqual(self.host_ref, ret)

    @mock.patch.object(vm_util, 'get_vm_ref')
    def test_get_host_name_for_vm(self, mock_get_vm_ref):
        mock_get_vm_ref.return_value = self.vm_ref

        host = fake._get_object(self.host_ref)

        ret = vm_util.get_host_name_for_vm(self.session, 'fake-instance')

        mock_get_vm_ref.assert_called_once_with(self.session, 'fake-instance')
        self.assertEqual(host.name, ret)
