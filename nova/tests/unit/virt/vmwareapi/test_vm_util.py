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

import mock
from oslo_utils import units
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
        stubs.set_stubs(self)
        vm_util.vm_refs_cache_reset()
        self._instance = fake_instance.fake_instance_obj(
            None,
            **{'id': 7, 'name': 'fake!',
               'display_name': 'fake-display-name',
               'uuid': uuidutils.generate_uuid(),
               'vcpus': 2, 'memory_mb': 2048})

    def _test_get_stats_from_cluster(self, connection_state="connected",
                                     maintenance_mode=False):
        ManagedObjectRefs = [fake.ManagedObjectReference("HostSystem",
                                                         "host1"),
                             fake.ManagedObjectReference("HostSystem",
                                                         "host2")]
        hosts = fake._convert_to_array_of_mor(ManagedObjectRefs)
        respool = fake.ManagedObjectReference("ResourcePool", "resgroup-11")
        prop_dict = {'host': hosts, 'resourcePool': respool}

        hardware = fake.DataObject()
        hardware.numCpuCores = 8
        hardware.numCpuThreads = 16
        hardware.vendor = "Intel"
        hardware.cpuModel = "Intel(R) Xeon(R)"
        hardware.memorySize = 4 * units.Gi

        runtime_host_1 = fake.DataObject()
        runtime_host_1.connectionState = "connected"
        runtime_host_1.inMaintenanceMode = False

        quickstats_1 = fake.DataObject()
        quickstats_1.overallMemoryUsage = 512

        quickstats_2 = fake.DataObject()
        quickstats_2.overallMemoryUsage = 512

        runtime_host_2 = fake.DataObject()
        runtime_host_2.connectionState = connection_state
        runtime_host_2.inMaintenanceMode = maintenance_mode

        prop_list_host_1 = [fake.Prop(name="summary.hardware", val=hardware),
                            fake.Prop(name="summary.runtime",
                                      val=runtime_host_1),
                            fake.Prop(name="summary.quickStats",
                                      val=quickstats_1)]
        prop_list_host_2 = [fake.Prop(name="summary.hardware", val=hardware),
                            fake.Prop(name="summary.runtime",
                                      val=runtime_host_2),
                            fake.Prop(name="summary.quickStats",
                                      val=quickstats_2)]

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.ObjectContent("prop_list_host1",
                                                   prop_list_host_1))
        fake_objects.add_object(fake.ObjectContent("prop_list_host1",
                                                   prop_list_host_2))

        def fake_call_method(*args):
            if "get_object_properties_dict" in args:
                return prop_dict
            elif "get_properties_for_a_collection_of_objects" in args:
                return fake_objects
            else:
                raise Exception('unexpected method call')

        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method', fake_call_method):
            result = vm_util.get_stats_from_cluster(session, "cluster1")
            if connection_state == "connected" and not maintenance_mode:
                num_hosts = 2
            else:
                num_hosts = 1
            expected_stats = {'cpu': {'vcpus': num_hosts * 16,
                                      'max_vcpus_per_host': 16},
                              'mem': {'total': num_hosts * 4096,
                                      'free': num_hosts * 4096 -
                                              num_hosts * 512,
                                      'max_mem_mb_per_host': 4096}}
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
        cpu_limits = vm_util.Limits(limit=7,
                                    reservation=6)
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

    def test_update_vif_spec_opaque_net(self):
        fake_factory = fake.FakeFactory()
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'OpaqueNetwork',
                            'network-id': 'fake-network-id',
                            'network-type': 'fake-net',
                            'use-external-id': False},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        device = fake_factory.create('ns0:VirtualDevice')
        actual = vm_util.update_vif_spec(fake_factory, vif_info, device)
        spec = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        spec.device = fake_factory.create('ns0:VirtualDevice')
        spec.device.backing = fake_factory.create(
            'ns0:VirtualEthernetCardOpaqueNetworkBackingInfo')
        spec.device.backing.opaqueNetworkType = 'fake-net'
        spec.device.backing.opaqueNetworkId = 'fake-network-id'
        spec.operation = 'edit'
        self.assertEqual(spec, actual)

    def test_update_vif_spec_dvpg(self):
        fake_factory = fake.FakeFactory()
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        device = fake_factory.create('ns0:VirtualDevice')
        actual = vm_util.update_vif_spec(fake_factory, vif_info, device)
        spec = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        spec.device = fake_factory.create('ns0:VirtualDevice')
        spec.device.backing = fake_factory.create(
            'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo')
        spec.device.backing.port = fake_factory.create(
            'ns0:DistributedVirtualSwitchPortConnection')
        spec.device.backing.port.portgroupKey = 'fake-group'
        spec.device.backing.port.switchUuid = 'fake-network-id'
        spec.operation = 'edit'
        self.assertEqual(spec, actual)

    def test_update_vif_spec_network(self):
        fake_factory = fake.FakeFactory()
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'Network',
                            'name': 'net1'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        device = fake_factory.create('ns0:VirtualDevice')
        actual = vm_util.update_vif_spec(fake_factory, vif_info, device)
        spec = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        spec.device = fake_factory.create('ns0:VirtualDevice')
        spec.device.backing = fake_factory.create(
            'ns0:VirtualEthernetCardNetworkBackingInfo')
        spec.device.backing.deviceName = 'br100'
        spec.operation = 'edit'
        self.assertEqual(spec, actual)

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
                          adapter_type=constants.ADAPTER_TYPE_LSILOGICSAS)
        self.assertEqual("ns0:VirtualLsiLogicSASController",
                         config_spec.device.obj_name)

    def test_paravirtual_controller_spec(self):
        # Test controller spec returned for paraVirtual adapter type
        config_spec = vm_util.create_controller_spec(fake.FakeFactory(), -101,
                          adapter_type=constants.ADAPTER_TYPE_PARAVIRTUAL)
        self.assertEqual("ns0:ParaVirtualSCSIController",
                         config_spec.device.obj_name)

    def test_create_controller_spec_with_specific_bus_number(self):
        # Test controller spec with specific bus number rather default 0
        config_spec = vm_util.create_controller_spec(fake.FakeFactory(), -101,
                          adapter_type=constants.ADAPTER_TYPE_LSILOGICSAS,
                          bus_number=1)
        self.assertEqual(1, config_spec.device.busNumber)

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
            self.assertEqual(constants.ADAPTER_TYPE_LSILOGICSAS,
                             vmdk.adapter_type)
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
            self.assertEqual(constants.ADAPTER_TYPE_LSILOGICSAS,
                             vmdk.adapter_type)
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
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type(
            constants.DEFAULT_ADAPTER_TYPE)
        self.assertEqual(constants.DEFAULT_ADAPTER_TYPE, vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type(
            constants.ADAPTER_TYPE_LSILOGICSAS)
        self.assertEqual(constants.DEFAULT_ADAPTER_TYPE, vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type(
            constants.ADAPTER_TYPE_PARAVIRTUAL)
        self.assertEqual(constants.DEFAULT_ADAPTER_TYPE, vmdk_adapter_type)
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

    def test_get_bus_number_for_scsi_controller(self):
        devices = [fake.VirtualLsiLogicController(1000, scsiCtlrUnitNumber=7,
                                                  busNumber=0),
                   fake.VirtualLsiLogicController(1002, scsiCtlrUnitNumber=7,
                                                  busNumber=2)]
        bus_number = vm_util._get_bus_number_for_scsi_controller(devices)
        self.assertEqual(1, bus_number)

    def test_get_bus_number_for_scsi_controller_buses_used_up(self):
        devices = [fake.VirtualLsiLogicController(1000, scsiCtlrUnitNumber=7,
                                                  busNumber=0),
                   fake.VirtualLsiLogicController(1001, scsiCtlrUnitNumber=7,
                                                  busNumber=1),
                   fake.VirtualLsiLogicController(1002, scsiCtlrUnitNumber=7,
                                                  busNumber=2),
                   fake.VirtualLsiLogicController(1003, scsiCtlrUnitNumber=7,
                                                  busNumber=3)]
        self.assertRaises(vexc.VMwareDriverException,
                          vm_util._get_bus_number_for_scsi_controller,
                          devices)

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
                                                constants.DEFAULT_ADAPTER_TYPE)
        self.assertEqual(1000, controller_key)
        self.assertEqual(8, unit_number)
        self.assertIsNone(controller_spec)

    def test_allocate_controller_key_and_unit_number_scsi_new_controller(self):
        # Test that we allocate on existing SCSI controller if there is a free
        # slot on it
        devices = [fake.VirtualLsiLogicController(1000, scsiCtlrUnitNumber=15)]
        for unit_number in range(15):
            disk = fake.VirtualDisk(1000, unit_number)
            devices.append(disk)
        factory = fake.FakeFactory()
        (controller_key, unit_number,
         controller_spec) = vm_util.allocate_controller_key_and_unit_number(
                                                factory,
                                                devices,
                                                constants.DEFAULT_ADAPTER_TYPE)
        self.assertEqual(-101, controller_key)
        self.assertEqual(0, unit_number)
        self.assertEqual(1, controller_spec.device.busNumber)

    def test_get_vnc_config_spec(self):
        self.flags(vnc_keymap='en-ie', group='vmware')
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vnc_config_spec(fake_factory, 7)
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

        remote_display_vnc_keymap = fake_factory.create('ns0:OptionValue')
        remote_display_vnc_keymap.value = 'en-ie'
        remote_display_vnc_keymap.key = 'RemoteDisplay.vnc.keyMap'
        expected.extraConfig.append(remote_display_vnc_keymap)

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

    def test_get_cluster_ref_by_name_none(self):
        fake_objects = fake.FakeRetrieveResult()
        ref = vm_util.get_cluster_ref_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), 'fake_cluster')
        self.assertIsNone(ref)

    def test_get_cluster_ref_by_name_exists(self):
        fake_objects = fake.FakeRetrieveResult()
        cluster = fake.ClusterComputeResource(name='cluster')
        fake_objects.add_object(cluster)
        ref = vm_util.get_cluster_ref_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), 'cluster')
        self.assertIs(cluster.obj, ref)

    def test_get_cluster_ref_by_name_missing(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(partialObject(path='cluster'))
        ref = vm_util.get_cluster_ref_by_name(
            fake.FakeObjectRetrievalSession(fake_objects), 'cluster')
        self.assertIsNone(ref)

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

    def _create_vm_config_spec(self):
        fake_factory = fake.FakeFactory()
        spec = fake_factory.create('ns0:VirtualMachineConfigSpec')
        spec.name = self._instance.uuid
        spec.instanceUuid = self._instance.uuid
        spec.deviceChange = []
        spec.numCPUs = 2

        spec.version = None
        spec.memoryMB = 2048
        spec.guestId = 'otherGuest'
        spec.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        spec.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        spec.extraConfig.append(extra_config)
        spec.files = fake_factory.create('ns0:VirtualMachineFileInfo')
        spec.files.vmPathName = '[fake-datastore]'

        spec.managedBy = fake_factory.create('ns0:ManagedByInfo')
        spec.managedBy.extensionKey = 'org.openstack.compute'
        spec.managedBy.type = 'instance'

        spec.tools = fake_factory.create('ns0:ToolsConfigInfo')
        spec.tools.afterPowerOn = True
        spec.tools.afterResume = True
        spec.tools.beforeGuestReboot = True
        spec.tools.beforeGuestShutdown = True
        spec.tools.beforeGuestStandby = True
        return spec

    def test_get_vm_extra_config_spec(self):

        fake_factory = fake.FakeFactory()
        extra_opts = {mock.sentinel.key: mock.sentinel.value}
        res = vm_util.get_vm_extra_config_spec(fake_factory, extra_opts)

        self.assertEqual(1, len(res.extraConfig))
        self.assertEqual(mock.sentinel.key, res.extraConfig[0].key)
        self.assertEqual(mock.sentinel.value, res.extraConfig[0].value)

    def test_get_vm_create_spec(self):
        extra_specs = vm_util.ExtraSpecs()
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)

        expected = self._create_vm_config_spec()
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_serial_port(self):
        extra_specs = vm_util.ExtraSpecs()
        fake_factory = fake.FakeFactory()
        self.flags(serial_port_service_uri='foobar', group='vmware')
        self.flags(serial_port_proxy_uri='telnet://example.com:31337',
                   group='vmware')
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)

        serial_port_spec = vm_util.create_serial_port_spec(fake_factory)
        expected = self._create_vm_config_spec()
        expected.deviceChange = [serial_port_spec]
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_allocations(self):
        cpu_limits = vm_util.Limits(limit=7,
                                    reservation=6)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs)
        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.deviceChange = []
        expected.guestId = constants.DEFAULT_OS_TYPE
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
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_limit(self):
        cpu_limits = vm_util.Limits(limit=7)
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
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        expected.version = None
        expected.guestId = constants.DEFAULT_OS_TYPE

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
        cpu_limits = vm_util.Limits(shares_level='high')
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
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048

        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.type = 'instance'
        expected.managedBy.extensionKey = 'org.openstack.compute'

        expected.version = None
        expected.guestId = constants.DEFAULT_OS_TYPE

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
        cpu_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=1948)
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
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)

        expected.memoryMB = 2048
        expected.managedBy = fake_factory.create('ns0:ManagedByInfo')
        expected.managedBy.extensionKey = 'org.openstack.compute'
        expected.managedBy.type = 'instance'

        expected.version = None
        expected.guestId = constants.DEFAULT_OS_TYPE
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

    def test_get_vm_create_spec_with_metadata(self):
        extra_specs = vm_util.ExtraSpecs()
        fake_factory = fake.FakeFactory()
        result = vm_util.get_vm_create_spec(fake_factory,
                                            self._instance,
                                            'fake-datastore', [],
                                            extra_specs,
                                            metadata='fake-metadata')

        expected = fake_factory.create('ns0:VirtualMachineConfigSpec')
        expected.name = self._instance.uuid
        expected.instanceUuid = self._instance.uuid
        expected.deviceChange = []
        expected.numCPUs = 2

        expected.version = None
        expected.memoryMB = 2048
        expected.guestId = 'otherGuest'
        expected.annotation = 'fake-metadata'
        expected.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
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

    def test_get_vm_create_spec_with_firmware(self):
        extra_specs = vm_util.ExtraSpecs(firmware='efi')
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
        expected.firmware = 'efi'
        expected.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
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

    def test_create_vm(self):

        def fake_call_method(module, method, *args, **kwargs):
            if (method == 'CreateVM_Task'):
                return 'fake_create_vm_task'
            else:
                self.fail('Should not get here....')

        def fake_wait_for_task(self, *args):
            task_info = mock.Mock(state="success", result="fake_vm_ref")
            return task_info

        session = fake.FakeSession()
        fake_call_mock = mock.Mock(side_effect=fake_call_method)
        fake_wait_mock = mock.Mock(side_effect=fake_wait_for_task)
        with test.nested(
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
                 "VirtualVmxnet", "VirtualVmxnet3"]
        for type in types:
            self.assertEqual(type,
                             vm_util.convert_vif_model(type))
        self.assertRaises(exception.Invalid,
                          vm_util.convert_vif_model,
                          "InvalidVifModel")

    def test_power_on_instance_with_vm_ref(self):
        session = fake.FakeSession()
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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

    def test_reconfigure_vm(self):
        session = fake.FakeSession()
        with test.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake_reconfigure_task'),
            mock.patch.object(session, '_wait_for_task')
        ) as (_call_method, _wait_for_task):
            vm_util.reconfigure_vm(session, 'fake-ref', 'fake-spec')
            _call_method.assert_called_once_with(mock.ANY,
                'ReconfigVM_Task', 'fake-ref', spec='fake-spec')
            _wait_for_task.assert_called_once_with(
                'fake_reconfigure_task')

    def _get_network_attach_config_spec_opaque(self, network_ref,
                                               vc6_onwards=False):
        vif_info = {'network_name': 'fake-name',
                    'mac_address': '00:00:00:ca:fe:01',
                    'network_ref': network_ref,
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
        if network_ref['use-external-id']:
            if vc6_onwards:
                device.externalId = vif_info['iface_id']
            else:
                dp = fake_factory.create('ns0:DynamicProperty')
                dp.name = '__externalId__'
                dp.val = vif_info['iface_id']
                device.dynamicProperty = [dp]
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

    def test_get_network_attach_config_spec_opaque_integration_bridge(self):
        network_ref = {'type': 'OpaqueNetwork',
                       'network-id': 'fake-network-id',
                       'network-type': 'opaque',
                       'use-external-id': False}
        self._get_network_attach_config_spec_opaque(network_ref)

    def test_get_network_attach_config_spec_opaque(self):
        network_ref = {'type': 'OpaqueNetwork',
                       'network-id': 'fake-network-id',
                       'network-type': 'nsx.LogicalSwitch',
                       'use-external-id': True}
        self._get_network_attach_config_spec_opaque(network_ref)

    @mock.patch.object(fake, 'DataObject')
    def test_get_network_attach_config_spec_opaque_vc6_onwards(self,
                                                               mock_object):
        # Add new attribute externalId supported from VC6
        class FakeVirtualE1000(fake.DataObject):
            def __init__(self):
                super(FakeVirtualE1000, self).__init__()
                self.externalId = None

        mock_object.return_value = FakeVirtualE1000
        network_ref = {'type': 'OpaqueNetwork',
                       'network-id': 'fake-network-id',
                       'network-type': 'nsx.LogicalSwitch',
                       'use-external-id': True}
        self._get_network_attach_config_spec_opaque(network_ref,
                                                    vc6_onwards=True)

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

    def test_get_network_attach_config_spec_dvs_with_limits(self):
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        fake_factory = fake.FakeFactory()

        limits = vm_util.Limits()
        limits.limit = 10
        limits.reservation = 20
        limits.shares_level = 'custom'
        limits.shares_share = 40
        result = vm_util.get_network_attach_config_spec(
                fake_factory, vif_info, 1, limits)
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

        device.resourceAllocation = fake_factory.create(
            'ns0:VirtualEthernetCardResourceAllocation')
        device.resourceAllocation.limit = 10
        device.resourceAllocation.reservation = 20
        device.resourceAllocation.share = fake_factory.create(
            'ns0:SharesInfo')
        device.resourceAllocation.share.level = 'custom'
        device.resourceAllocation.share.shares = 40

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.connected = True
        connectable.startConnected = True
        device.connectable = connectable
        device_change.device = device

        expected.deviceChange.append(device_change)
        self.assertEqual(expected, result)

    def _get_create_vif_spec(self, fake_factory, vif_info):
        limits = vm_util.Limits()
        limits.limit = 10
        limits.reservation = 20
        limits.shares_level = 'custom'
        limits.shares_share = 40
        return vm_util._create_vif_spec(fake_factory, vif_info, limits)

    def _construct_vif_spec(self, fake_factory, vif_info):
        port = 'ns0:DistributedVirtualSwitchPortConnection'
        backing = 'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo'

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
        if vif_info['network_ref'].get('dvs_port_key'):
            device.backing.port.portKey = (
                vif_info['network_ref']['dvs_port_key'])

        device.resourceAllocation = fake_factory.create(
            'ns0:VirtualEthernetCardResourceAllocation')
        device.resourceAllocation.limit = 10
        device.resourceAllocation.reservation = 20
        device.resourceAllocation.share = fake_factory.create(
            'ns0:SharesInfo')
        device.resourceAllocation.share.level = 'custom'
        device.resourceAllocation.share.shares = 40

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.connected = True
        connectable.startConnected = True
        device.connectable = connectable
        device_change.device = device
        return device_change

    def test_get_create_vif_spec(self):
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        fake_factory = fake.FakeFactory()
        result = self._get_create_vif_spec(fake_factory, vif_info)
        device_change = self._construct_vif_spec(fake_factory, vif_info)
        self.assertEqual(device_change, result)

    def test_get_create_vif_spec_dvs_port_key(self):
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id',
                            'dvpg': 'fake-group',
                            'dvs_port_key': 'fake-key'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        fake_factory = fake.FakeFactory()
        result = self._get_create_vif_spec(fake_factory, vif_info)
        device_change = self._construct_vif_spec(fake_factory, vif_info)
        self.assertEqual(device_change, result)

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
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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
        with test.nested(
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

    def test_vm_create_spec_with_multi_vifs(self):
        datastore = ds_obj.Datastore('fake-ds-ref', 'fake-ds-name')
        extra_specs = vm_util.ExtraSpecs()
        vif_info = {'network_name': 'br100',
            'mac_address': '00:00:00:ca:fe:01',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id1',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        vif_info2 = {'network_name': 'br101',
            'mac_address': '00:00:00:ca:fe:02',
            'network_ref': {'type': 'DistributedVirtualPortgroup',
                            'dvsw': 'fake-network-id2',
                            'dvpg': 'fake-group'},
            'iface_id': 7,
            'vif_model': 'VirtualE1000'}
        create_spec = vm_util.get_vm_create_spec(fake.FakeFactory(),
                                            self._instance,
                                            datastore.name,
                                            [vif_info, vif_info2],
                                            extra_specs)

        port = 'ns0:DistributedVirtualSwitchPortConnection'
        backing = 'ns0:VirtualEthernetCardDistributedVirtualPortBackingInfo'

        device_changes = []
        fake_factory = fake.FakeFactory()
        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.operation = 'add'

        device = fake_factory.create('ns0:VirtualE1000')
        device.key = -47
        device.macAddress = '00:00:00:ca:fe:01'
        device.addressType = 'manual'
        device.wakeOnLanEnabled = True

        device.backing = fake_factory.create(backing)
        device.backing.port = fake_factory.create(port)
        device.backing.port.portgroupKey = 'fake-group'
        device.backing.port.switchUuid = 'fake-network-id1'

        device.resourceAllocation = fake_factory.create(
            'ns0:VirtualEthernetCardResourceAllocation')
        device.resourceAllocation.share = fake_factory.create(
            'ns0:SharesInfo')
        device.resourceAllocation.share.level = None
        device.resourceAllocation.share.shares = None

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.connected = True
        connectable.startConnected = True
        device.connectable = connectable
        device_change.device = device

        device_changes.append(device_change)

        device_change = fake_factory.create('ns0:VirtualDeviceConfigSpec')
        device_change.operation = 'add'

        device = fake_factory.create('ns0:VirtualE1000')
        device.key = -48
        device.macAddress = '00:00:00:ca:fe:02'
        device.addressType = 'manual'
        device.wakeOnLanEnabled = True

        device.backing = fake_factory.create(backing)
        device.backing.port = fake_factory.create(port)
        device.backing.port.portgroupKey = 'fake-group'
        device.backing.port.switchUuid = 'fake-network-id2'

        device.resourceAllocation = fake_factory.create(
            'ns0:VirtualEthernetCardResourceAllocation')
        device.resourceAllocation.share = fake_factory.create(
            'ns0:SharesInfo')
        device.resourceAllocation.share.level = None
        device.resourceAllocation.share.shares = None

        connectable = fake_factory.create('ns0:VirtualDeviceConnectInfo')
        connectable.allowGuestControl = True
        connectable.connected = True
        connectable.startConnected = True
        device.connectable = connectable
        device_change.device = device

        device_changes.append(device_change)

        self.assertEqual(device_changes, create_spec.deviceChange)

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

    def test_validate_limits(self):
        limits = vm_util.Limits(shares_level='high',
                                shares_share=1948)
        self.assertRaises(exception.InvalidInput,
                          limits.validate)
        limits = vm_util.Limits(shares_level='fira')
        self.assertRaises(exception.InvalidInput,
                          limits.validate)

    def test_get_vm_create_spec_with_console_delay(self):
        extra_specs = vm_util.ExtraSpecs()
        self.flags(console_delay_seconds=2, group='vmware')
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
        expected.guestId = constants.DEFAULT_OS_TYPE
        expected.extraConfig = []

        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = self._instance.uuid
        extra_config.key = 'nvp.vm-uuid'
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = 2000000
        extra_config.key = 'keyboard.typematicMinDelay'
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

    def test_get_vm_create_spec_with_cores_per_socket(self):
        extra_specs = vm_util.ExtraSpecs(cores_per_socket=4)
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
        expected.numCoresPerSocket = 4
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

        expected.extraConfig = []
        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.key = 'nvp.vm-uuid'
        extra_config.value = self._instance.uuid
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)
        self.assertEqual(expected, result)

    def test_get_vm_create_spec_with_memory_allocations(self):
        memory_limits = vm_util.Limits(limit=7,
                                       reservation=6)
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
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

        memory_allocation = fake_factory.create('ns0:ResourceAllocationInfo')
        memory_allocation.limit = 7
        memory_allocation.reservation = 6
        memory_allocation.shares = fake_factory.create('ns0:SharesInfo')
        memory_allocation.shares.level = 'normal'
        memory_allocation.shares.shares = 0
        expected.memoryAllocation = memory_allocation

        expected.extraConfig = []
        extra_config = fake_factory.create('ns0:OptionValue')
        extra_config.key = 'nvp.vm-uuid'
        extra_config.value = self._instance.uuid
        expected.extraConfig.append(extra_config)
        extra_config = fake_factory.create("ns0:OptionValue")
        extra_config.value = True
        extra_config.key = 'disk.EnableUUID'
        expected.extraConfig.append(extra_config)
        self.assertEqual(expected, result)

    def test_get_swap(self):
        vm_ref = 'fake-vm-ref'

        # Root disk
        controller_key = 1000
        root_disk = fake.VirtualDisk()
        root_disk.controllerKey = controller_key
        disk_backing = fake.VirtualDiskFlatVer2BackingInfo()
        disk_backing.fileName = '[test_datastore] uuid/uuid.vmdk'
        root_disk.capacityInBytes = 1048576
        root_disk.backing = disk_backing

        # Swap disk
        swap_disk = fake.VirtualDisk()
        swap_disk.controllerKey = controller_key
        disk_backing = fake.VirtualDiskFlatVer2BackingInfo()
        disk_backing.fileName = "swap"
        swap_disk.capacityInBytes = 1024
        swap_disk.backing = disk_backing
        devices = [root_disk, swap_disk]

        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method',
                               return_value=devices) as mock_call:
            device = vm_util.get_swap(session, vm_ref)

            mock_call.assert_called_once_with(mock.ANY,
                "get_object_property", vm_ref, "config.hardware.device")
            self.assertEqual(swap_disk, device)

    def test_create_folder(self):
        """Test create_folder when the folder doesn't exist"""
        child_folder = mock.sentinel.child_folder
        session = fake.FakeSession()
        with mock.patch.object(session, '_call_method',
                               side_effect=[child_folder]):
            parent_folder = mock.sentinel.parent_folder
            parent_folder.value = 'parent-ref'
            child_name = 'child_folder'
            ret = vm_util.create_folder(session, parent_folder, child_name)

            self.assertEqual(child_folder, ret)
            session._call_method.assert_called_once_with(session.vim,
                                                         'CreateFolder',
                                                         parent_folder,
                                                         name=child_name)

    def test_create_folder_duplicate_name(self):
        """Test create_folder when the folder already exists"""
        session = fake.FakeSession()
        details = {'object': 'folder-1'}
        duplicate_exception = vexc.DuplicateName(details=details)
        with mock.patch.object(session, '_call_method',
                               side_effect=[duplicate_exception]):
            parent_folder = mock.sentinel.parent_folder
            parent_folder.value = 'parent-ref'
            child_name = 'child_folder'
            ret = vm_util.create_folder(session, parent_folder, child_name)

            self.assertEqual('Folder', ret._type)
            self.assertEqual('folder-1', ret.value)
            session._call_method.assert_called_once_with(session.vim,
                                                         'CreateFolder',
                                                         parent_folder,
                                                         name=child_name)

    def test_folder_path_ref_cache(self):
        path = 'OpenStack/Project (e2b86092bf064181ade43deb3188f8e4)'
        self.assertIsNone(vm_util.folder_ref_cache_get(path))
        vm_util.folder_ref_cache_update(path, 'fake-ref')
        self.assertEqual('fake-ref', vm_util.folder_ref_cache_get(path))

    def test_get_vm_name(self):
        uuid = uuidutils.generate_uuid()
        expected = uuid
        name = vm_util._get_vm_name(None, uuid)
        self.assertEqual(expected, name)

        display_name = 'fira'
        expected = 'fira (%s)' % uuid
        name = vm_util._get_vm_name(display_name, uuid)
        self.assertEqual(expected, name)

        display_name = 'X' * 255
        expected = '%s (%s)' % ('X' * 41, uuid)
        name = vm_util._get_vm_name(display_name, uuid)
        self.assertEqual(expected, name)
        self.assertEqual(len(name), 80)

    @mock.patch.object(vm_util, '_get_vm_name', return_value='fake-name')
    def test_rename_vm(self, mock_get_name):
        session = fake.FakeSession()
        with test.nested(
            mock.patch.object(session, '_call_method',
                              return_value='fake_rename_task'),
            mock.patch.object(session, '_wait_for_task')
        ) as (_call_method, _wait_for_task):
            vm_util.rename_vm(session, 'fake-ref', self._instance)
            _call_method.assert_called_once_with(mock.ANY,
                'Rename_Task', 'fake-ref', newName='fake-name')
            _wait_for_task.assert_called_once_with(
                'fake_rename_task')
        mock_get_name.assert_called_once_with(self._instance.display_name,
                                              self._instance.uuid)


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
        self.host_ref = list(fake._db_content['HostSystem'].keys())[0]
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
