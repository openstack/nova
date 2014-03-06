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
import re

import mock

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova import test
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import vm_util


class fake_session(object):
    def __init__(self, *ret):
        self.ret = ret
        self.ind = 0

    def _call_method(self, *args):
        # return fake objects in circular manner
        self.ind = (self.ind + 1) % len(self.ret)
        return self.ret[self.ind - 1]

    def _get_vim(self):
        fake_vim = fake.DataObject()
        client = fake.DataObject()
        client.factory = 'fake_factory'
        fake_vim.client = client
        return fake_vim


class partialObject(object):
    def __init__(self, path='fake-path'):
        self.path = path
        self.fault = fake.DataObject()


class VMwareVMUtilTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMUtilTestCase, self).setUp()
        fake.reset()
        vm_util.vm_refs_cache_reset()

    def tearDown(self):
        super(VMwareVMUtilTestCase, self).tearDown()
        fake.reset()

    def test_get_datastore_ref_and_name(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore())
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects))

        self.assertEqual(result[1], "fake-ds")
        self.assertEqual(result[2], units.Ti)
        self.assertEqual(result[3], 500 * units.Gi)

    def test_get_datastore_ref_and_name_with_regex(self):
        # Test with a regex that matches with a datastore
        datastore_valid_regex = re.compile("^openstack.*\d$")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects), None, None, datastore_valid_regex)
        self.assertEqual("openstack-ds0", result[1])

    def test_get_stats_from_cluster(self):
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
        runtime_host_2 = fake.DataObject()
        runtime_host_2.connectionState = "disconnected"

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

        fake_datastores = fake.FakeRetrieveResult()
        fake_datastores.add_object(fake.Datastore("fake-ds0"))
        fake_datastores.add_object(fake.Datastore("fake-ds1"))

        respool_resource_usage = fake.DataObject()
        respool_resource_usage.maxUsage = 5368709120
        respool_resource_usage.overallUsage = 2147483648
        session = fake_session()

        def fake_call_method(*args):
            if "get_dynamic_properties" in args:
                return prop_dict
            elif "get_properties_for_a_collection_of_objects" in args:
                return fake_objects
            elif "get_dynamic_property" in args:
                return respool_resource_usage
            elif "get_inner_objects" in args:
                return fake_datastores
        with mock.patch.object(fake_session, '_call_method',
                               fake_call_method):
            result = vm_util.get_stats_from_cluster(session, "cluster1")
            cpu_info = {}
            mem_info = {}
            disk_info = {}
            cpu_info['vcpus'] = 16
            cpu_info['cores'] = 8
            cpu_info['vendor'] = ["Intel"]
            cpu_info['model'] = ["Intel(R) Xeon(R)"]
            mem_info['total'] = 5120
            mem_info['free'] = 3072
            disk_info['free'] = 1000
            disk_info['total'] = 2048
            expected_stats = {'cpu': cpu_info, 'mem': mem_info,
                              'disk': disk_info}
            self.assertEqual(expected_stats, result)

    def test_get_datastore_ref_and_name_with_token(self):
        regex = re.compile("^ds.*\d$")
        fake0 = fake.FakeRetrieveResult()
        fake0.add_object(fake.Datastore("ds0", 10 * units.Gi, 5 * units.Gi))
        fake0.add_object(fake.Datastore("foo", 10 * units.Gi, 9 * units.Gi))
        setattr(fake0, 'token', 'token-0')
        fake1 = fake.FakeRetrieveResult()
        fake1.add_object(fake.Datastore("ds2", 10 * units.Gi, 8 * units.Gi))
        fake1.add_object(fake.Datastore("ds3", 10 * units.Gi, 1 * units.Gi))
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake0, fake1), None, None, regex)
        self.assertEqual("ds2", result[1])

    def test_get_datastore_ref_and_name_with_list(self):
        # Test with a regex containing whitelist of datastores
        datastore_valid_regex = re.compile("(openstack-ds0|openstack-ds2)")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("openstack-ds1"))
        fake_objects.add_object(fake.Datastore("openstack-ds2"))
        result = vm_util.get_datastore_ref_and_name(
            fake_session(fake_objects), None, None, datastore_valid_regex)
        self.assertNotEqual("openstack-ds1", result[1])

    def test_get_datastore_ref_and_name_with_regex_error(self):
        # Test with a regex that has no match
        # Checks if code raises DatastoreNotFound with a specific message
        datastore_invalid_regex = re.compile("unknown-ds")
        exp_message = (_("Datastore regex %s did not match any datastores")
                       % datastore_invalid_regex.pattern)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))
        # assertRaisesRegExp would have been a good choice instead of
        # try/catch block, but it's available only from Py 2.7.
        try:
            vm_util.get_datastore_ref_and_name(
                fake_session(fake_objects), None, None,
                datastore_invalid_regex)
        except exception.DatastoreNotFound as e:
            self.assertEqual(exp_message, e.args[0])
        else:
            self.fail("DatastoreNotFound Exception was not raised with "
                      "message: %s" % exp_message)

    def test_get_datastore_ref_and_name_without_datastore(self):

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(None), host="fake-host")

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(None), cluster="fake-cluster")

    def test_get_host_ref_from_id(self):
        fake_host_name = "ha-host"
        fake_host_sys = fake.HostSystem(fake_host_name)
        fake_host_id = fake_host_sys.obj.value
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake_host_sys)
        ref = vm_util.get_host_ref_from_id(
            fake_session(fake_objects), fake_host_id, ['name'])

        self.assertIsInstance(ref, fake.HostSystem)
        self.assertEqual(fake_host_id, ref.obj.value)

        host_name = vm_util.get_host_name_from_host_ref(ref)

        self.assertEqual(fake_host_name, host_name)

    def test_get_host_ref_no_hosts_in_cluster(self):
        self.assertRaises(exception.NoValidHost,
                          vm_util.get_host_ref,
                          fake_session(""), 'fake_cluster')

    def test_get_datastore_ref_and_name_no_host_in_cluster(self):
        self.assertRaises(exception.DatastoreNotFound,
                          vm_util.get_datastore_ref_and_name,
                          fake_session(""), 'fake_cluster')

    @mock.patch.object(vm_util, '_get_vm_ref_from_vm_uuid',
                       return_value=None)
    def test_get_host_name_for_vm(self, _get_ref_from_uuid):
        fake_host = fake.HostSystem()
        fake_host_id = fake_host.obj.value
        fake_vm = fake.VirtualMachine(name='vm-123',
                                      runtime_host=fake_host.obj)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake_vm)

        vm_ref = vm_util.get_vm_ref_from_name(
                fake_session(fake_objects), 'vm-123')

        self.assertIsNotNone(vm_ref)

        host_id = vm_util.get_host_id_from_vm_ref(
            fake_session(fake_objects), vm_ref)

        self.assertEqual(fake_host_id, host_id)

    def test_property_from_property_set(self):

        ObjectContent = collections.namedtuple('ObjectContent', ['propSet'])
        DynamicProperty = collections.namedtuple('Property', ['name', 'val'])
        MoRef = collections.namedtuple('Val', ['value'])

        good_objects = fake.FakeRetrieveResult()
        results_good = [
            ObjectContent(propSet=[
                DynamicProperty(name='name', val=MoRef(value='vm-123'))]),
            ObjectContent(propSet=[
                DynamicProperty(name='foo', val=MoRef(value='bar1')),
                DynamicProperty(
                    name='runtime.host', val=MoRef(value='host-123')),
                DynamicProperty(name='foo', val=MoRef(value='bar2')),
            ]),
            ObjectContent(propSet=[
                DynamicProperty(
                    name='something', val=MoRef(value='thing'))]), ]
        for result in results_good:
            good_objects.add_object(result)

        bad_objects = fake.FakeRetrieveResult()
        results_bad = [
            ObjectContent(propSet=[
                DynamicProperty(name='name', val=MoRef(value='vm-123'))]),
            ObjectContent(propSet=[
                DynamicProperty(name='foo', val='bar1'),
                DynamicProperty(name='foo', val='bar2'), ]),
            ObjectContent(propSet=[
                DynamicProperty(
                    name='something', val=MoRef(value='thing'))]), ]
        for result in results_bad:
            bad_objects.add_object(result)

        prop = vm_util.property_from_property_set(
                    'runtime.host', good_objects)
        self.assertIsNotNone(prop)
        value = prop.val.value
        self.assertEqual('host-123', value)

        prop2 = vm_util.property_from_property_set(
                    'runtime.host', bad_objects)
        self.assertIsNone(prop2)

        prop3 = vm_util.property_from_property_set('foo', good_objects)
        self.assertIsNotNone(prop3)
        val3 = prop3.val.value
        self.assertEqual('bar1', val3)

        prop4 = vm_util.property_from_property_set('foo', bad_objects)
        self.assertIsNotNone(prop4)
        self.assertEqual('bar1', prop4.val)

    def test_get_datastore_ref_and_name_inaccessible_ds(self):
        data_store = fake.Datastore()
        data_store.set("summary.accessible", False)

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(data_store)

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(fake_objects))

    def test_get_resize_spec(self):
        fake_instance = {'id': 7, 'name': 'fake!',
                         'uuid': 'bda5fb9e-b347-40e8-8256-42397848cb00',
                         'vcpus': 2, 'memory_mb': 2048}
        result = vm_util.get_vm_resize_spec(fake.FakeFactory(),
                                            fake_instance)
        expected = """{'memoryMB': 2048,
                       'numCPUs': 2,
                       'obj_name': 'ns0:VirtualMachineConfigSpec'}"""
        expected = re.sub(r'\s+', '', expected)
        result = re.sub(r'\s+', '', repr(result))
        self.assertEqual(expected, result)

    def test_get_cdrom_attach_config_spec(self):

        result = vm_util.get_cdrom_attach_config_spec(fake.FakeFactory(),
                                             fake.Datastore(),
                                             "/tmp/foo.iso",
                                             200, 0)
        expected = """{
    'deviceChange': [
        {
            'device': {
                'connectable': {
                    'allowGuestControl': False,
                    'startConnected': True,
                    'connected': True,
                    'obj_name': 'ns0: VirtualDeviceConnectInfo'
                },
                'backing': {
                    'datastore': {
                        "summary.type": "VMFS",
                        "summary.accessible":true,
                        "summary.name": "fake-ds",
                        "summary.capacity": 1099511627776,
                        "summary.freeSpace": 536870912000,
                        "browser": ""
                    },
                    'fileName': '/tmp/foo.iso',
                    'obj_name': 'ns0: VirtualCdromIsoBackingInfo'
                },
                'controllerKey': 200,
                'unitNumber': 0,
                'key': -1,
                'obj_name': 'ns0: VirtualCdrom'
            },
            'operation': 'add',
            'obj_name': 'ns0: VirtualDeviceConfigSpec'
        }
    ],
    'obj_name': 'ns0: VirtualMachineConfigSpec'
}
"""

        expected = re.sub(r'\s+', '', expected)
        result = re.sub(r'\s+', '', repr(result))
        self.assertEqual(expected, result)

    def test_lsilogic_controller_spec(self):
        # Test controller spec returned for lsiLogic sas adapter type
        config_spec = vm_util.create_controller_spec(fake.FakeFactory(), -101,
                          adapter_type="lsiLogicsas")
        self.assertEqual("ns0:VirtualLsiLogicSASController",
                          config_spec.device.obj_name)

    def _vmdk_path_and_adapter_type_devices(self, filename, parent=None):
        # Test the adapter_type returned for a lsiLogic sas controller
        controller_key = 1000
        disk = fake.VirtualDisk()
        disk.controllerKey = controller_key
        disk_backing = fake.VirtualDiskFlatVer2BackingInfo()
        disk_backing.fileName = filename
        if parent:
            disk_backing.parent = parent
        disk.backing = disk_backing
        controller = fake.VirtualLsiLogicSASController()
        controller.key = controller_key
        devices = [disk, controller]
        return devices

    def test_get_vmdk_path_and_adapter_type(self):
        filename = '[test_datastore] test_file.vmdk'
        devices = self._vmdk_path_and_adapter_type_devices(filename)
        vmdk_info = vm_util.get_vmdk_path_and_adapter_type(devices)
        adapter_type = vmdk_info[1]
        self.assertEqual('lsiLogicsas', adapter_type)
        self.assertEqual(vmdk_info[0], filename)

    def test_get_vmdk_path_and_adapter_type_with_match(self):
        n_filename = '[test_datastore] uuid/uuid.vmdk'
        devices = self._vmdk_path_and_adapter_type_devices(n_filename)
        vmdk_info = vm_util.get_vmdk_path_and_adapter_type(
                devices, uuid='uuid')
        adapter_type = vmdk_info[1]
        self.assertEqual('lsiLogicsas', adapter_type)
        self.assertEqual(n_filename, vmdk_info[0])

    def test_get_vmdk_path_and_adapter_type_with_nomatch(self):
        n_filename = '[test_datastore] diuu/diuu.vmdk'
        devices = self._vmdk_path_and_adapter_type_devices(n_filename)
        vmdk_info = vm_util.get_vmdk_path_and_adapter_type(
                devices, uuid='uuid')
        adapter_type = vmdk_info[1]
        self.assertEqual('lsiLogicsas', adapter_type)
        self.assertIsNone(vmdk_info[0])

    def test_get_vmdk_adapter_type(self):
        # Test for the adapter_type to be used in vmdk descriptor
        # Adapter type in vmdk descriptor is same for LSI-SAS & LSILogic
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("lsiLogic")
        self.assertEqual("lsiLogic", vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("lsiLogicsas")
        self.assertEqual("lsiLogic", vmdk_adapter_type)
        vmdk_adapter_type = vm_util.get_vmdk_adapter_type("dummyAdapter")
        self.assertEqual("dummyAdapter", vmdk_adapter_type)

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

    def _test_get_vnc_config_spec(self, port):

        result = vm_util.get_vnc_config_spec(fake.FakeFactory(),
                                             port)
        return result

    def test_get_vnc_config_spec(self):
        result = self._test_get_vnc_config_spec(7)
        expected = """{'extraConfig': [
                          {'value': 'true',
                           'key': 'RemoteDisplay.vnc.enabled',
                           'obj_name': 'ns0:OptionValue'},
                          {'value': 7,
                           'key': 'RemoteDisplay.vnc.port',
                           'obj_name': 'ns0:OptionValue'}],
                       'obj_name': 'ns0:VirtualMachineConfigSpec'}"""
        expected = re.sub(r'\s+', '', expected)
        result = re.sub(r'\s+', '', repr(result))
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
        actual = vm_util.get_vnc_port(fake_session(fake_vms))
        self.assertEqual(actual, 5910)

    def test_get_vnc_port_exhausted(self):
        fake_vms = self._create_fake_vms()
        self.flags(vnc_port=5900, group='vmware')
        self.flags(vnc_port_total=10, group='vmware')
        self.assertRaises(exception.ConsolePortRangeExhausted,
                          vm_util.get_vnc_port,
                          fake_session(fake_vms))

    def test_get_all_cluster_refs_by_name_none(self):
        fake_objects = fake.FakeRetrieveResult()
        refs = vm_util.get_all_cluster_refs_by_name(fake_session(fake_objects),
                                                    ['fake_cluster'])
        self.assertTrue(not refs)

    def test_get_all_cluster_refs_by_name_exists(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.ClusterComputeResource(name='cluster'))
        refs = vm_util.get_all_cluster_refs_by_name(fake_session(fake_objects),
                                                    ['cluster'])
        self.assertTrue(len(refs) == 1)

    def test_get_all_cluster_refs_by_name_missing(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(partialObject(path='cluster'))
        refs = vm_util.get_all_cluster_refs_by_name(fake_session(fake_objects),
                                                    ['cluster'])
        self.assertTrue(not refs)

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
        instance_uuid = uuidutils.generate_uuid()
        fake_instance = {'id': 7, 'name': 'fake!',
                         'uuid': instance_uuid,
                         'vcpus': 2, 'memory_mb': 2048}
        result = vm_util.get_vm_create_spec(fake.FakeFactory(),
                                            fake_instance, instance_uuid,
                                            'fake-datastore', [])
        expected = """{
            'files': {'vmPathName': '[fake-datastore]',
            'obj_name': 'ns0:VirtualMachineFileInfo'},
            'instanceUuid': '%(instance_uuid)s',
            'name': '%(instance_uuid)s', 'deviceChange': [],
            'extraConfig': [{'value': '%(instance_uuid)s',
                             'key': 'nvp.vm-uuid',
                             'obj_name': 'ns0:OptionValue'}],
            'memoryMB': 2048,
            'obj_name': 'ns0:VirtualMachineConfigSpec',
            'guestId': 'otherGuest',
            'tools': {'beforeGuestStandby': True,
                      'beforeGuestReboot': True,
                      'beforeGuestShutdown': True,
                      'afterResume': True,
                      'afterPowerOn': True,
            'obj_name': 'ns0:ToolsConfigInfo'},
            'numCPUs': 2}""" % {'instance_uuid': instance_uuid}
        expected = re.sub(r'\s+', '', expected)
        result = re.sub(r'\s+', '', repr(result))
        self.assertEqual(expected, result)
