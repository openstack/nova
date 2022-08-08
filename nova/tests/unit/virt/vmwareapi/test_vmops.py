# Copyright 2013 OpenStack Foundation
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

import time

import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units
from oslo_utils import uuidutils
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import vim_util as vutil

from nova.compute import power_state
from nova import context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova import version
from nova.virt import hardware
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import images
from nova.virt.vmwareapi import vif
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops


class DsPathMatcher(object):
    def __init__(self, expected_ds_path_str):
        self.expected_ds_path_str = expected_ds_path_str

    def __eq__(self, ds_path_param):
        return str(ds_path_param) == self.expected_ds_path_str


class VMwareVMOpsTestCase(test.TestCase):
    def setUp(self):
        super(VMwareVMOpsTestCase, self).setUp()
        ds_util.dc_cache_reset()
        vmwareapi_fake.reset()
        stubs.set_stubs(self)
        self.flags(enabled=True, group='vnc')
        self.flags(subdirectory_name='vmware_base', group='image_cache')
        self.flags(my_ip='',
                   flat_injected=True)
        self._context = context.RequestContext('fake_user', 'fake_project')
        self._session = driver.VMwareAPISession()

        self._virtapi = mock.Mock()
        self._image_id = uuids.image
        fake_ds_ref = vmwareapi_fake.ManagedObjectReference(value='fake-ds')
        self._ds = ds_obj.Datastore(
                ref=fake_ds_ref, name='fake_ds',
                capacity=10 * units.Gi,
                freespace=10 * units.Gi)
        self._dc_info = ds_util.DcInfo(
                ref='fake_dc_ref', name='fake_dc',
                vmFolder='fake_vm_folder')
        cluster = vmwareapi_fake.create_cluster('fake_cluster', fake_ds_ref)
        self._uuid = uuids.foo
        fake_info_cache = {
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            'instance_uuid': self._uuid,
            'network_info': '[]',
        }
        self._instance_values = {
            'name': 'fake_name',
            'display_name': 'fake_display_name',
            'uuid': self._uuid,
            'vcpus': 1,
            'memory_mb': 512,
            'image_ref': self._image_id,
            'root_gb': 10,
            'node': '%s(%s)' % (cluster.mo_id, cluster.name),
            'info_cache': fake_info_cache,
            'expected_attrs': ['system_metadata', 'info_cache'],
        }
        self._instance = fake_instance.fake_instance_obj(
                                 self._context, **self._instance_values)
        self._flavor = objects.Flavor(name='m1.small', memory_mb=512, vcpus=1,
                                      root_gb=10, ephemeral_gb=0, swap=0,
                                      extra_specs={})
        self._instance.flavor = self._flavor

        self._vmops = vmops.VMwareVMOps(self._session, self._virtapi, None,
                                        cluster=cluster.obj)
        self._cluster = cluster
        self._image_meta = objects.ImageMeta.from_dict({'id': self._image_id,
                                                        'owner': ''})
        subnet_4 = network_model.Subnet(cidr='192.168.0.1/24',
                                        dns=[network_model.IP('192.168.0.1')],
                                        gateway=
                                            network_model.IP('192.168.0.1'),
                                        ips=[
                                            network_model.IP('192.168.0.100')],
                                        routes=None)
        subnet_6 = network_model.Subnet(cidr='dead:beef::1/64',
                                        dns=None,
                                        gateway=
                                            network_model.IP('dead:beef::1'),
                                        ips=[network_model.IP(
                                            'dead:beef::dcad:beff:feef:0')],
                                        routes=None)
        network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        subnets=[subnet_4, subnet_6],
                                        vlan=None,
                                        bridge_interface=None,
                                        injected=True)
        self._network_values = {
            'id': None,
            'address': 'DE:AD:BE:EF:00:00',
            'network': network,
            'type': network_model.VIF_TYPE_OVS,
            'devname': None,
            'ovs_interfaceid': None,
            'rxtx_cap': 3
        }
        self.network_info = network_model.NetworkInfo([
                network_model.VIF(**self._network_values)
        ])
        pure_IPv6_network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        subnets=[subnet_6],
                                        vlan=None,
                                        bridge_interface=None,
                                        injected=True)
        self.pure_IPv6_network_info = network_model.NetworkInfo([
                network_model.VIF(id=None,
                                  address='DE:AD:BE:EF:00:00',
                                  network=pure_IPv6_network,
                                  type=None,
                                  devname=None,
                                  ovs_interfaceid=None,
                                  rxtx_cap=3)
                ])
        self._metadata = (
            "name:fake_display_name\n"
            "userid:fake_user\n"
            "username:None\n"
            "projectid:fake_project\n"
            "projectname:None\n"
            "flavor:name:m1.micro\n"
            "flavor:memory_mb:6\n"
            "flavor:vcpus:28\n"
            "flavor:ephemeral_gb:8128\n"
            "flavor:root_gb:496\n"
            "flavor:swap:33550336\n"
            "imageid:%s\n"
            "package:%s\n" % (
                uuids.image,
                version.version_string_with_package()))

    vm_util.vm_value_cache_update("test_id",
        'runtime.powerState', 'poweredOn')
    vm_util.vm_value_cache_update("fake_powered_off",
        'runtime.powerState', 'poweredOff')

    def test_get_machine_id_str(self):
        result = vmops.VMwareVMOps._get_machine_id_str(self.network_info)
        self.assertEqual('DE:AD:BE:EF:00:00;192.168.0.100;255.255.255.0;'
                         '192.168.0.1;192.168.0.255;192.168.0.1#', result)
        result = vmops.VMwareVMOps._get_machine_id_str(
                                        self.pure_IPv6_network_info)
        self.assertEqual('DE:AD:BE:EF:00:00;;;;;#', result)

    def _setup_create_folder_mocks(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        base_name = 'folder'
        ds_name = "datastore"
        ds_ref = vmwareapi_fake.ManagedObjectReference(value=1)
        dc_ref = mock.Mock()
        ds_util._DS_DC_MAPPING[ds_ref.value] = ds_util.DcInfo(
                ref=dc_ref,
                name='fake-name',
                vmFolder='fake-folder')
        path = ds_obj.DatastorePath(ds_name, base_name)
        return ds_name, ds_ref, ops, path, dc_ref

    @mock.patch.object(ds_util, 'mkdir')
    def test_create_folder_if_missing(self, mock_mkdir):
        ds_name, ds_ref, ops, path, dc = self._setup_create_folder_mocks()
        ops._create_folder_if_missing(ds_name, ds_ref, 'folder')
        mock_mkdir.assert_called_with(ops._session, path, dc)

    @mock.patch.object(ds_util, 'mkdir')
    def test_create_folder_if_missing_exception(self, mock_mkdir):
        ds_name, ds_ref, ops, path, dc = self._setup_create_folder_mocks()
        ds_util.mkdir.side_effect = vexc.FileAlreadyExistsException()
        ops._create_folder_if_missing(ds_name, ds_ref, 'folder')
        mock_mkdir.assert_called_with(ops._session, path, dc)

    def test_get_valid_vms_from_retrieve_result(self):
        ops = vmops.VMwareVMOps(self._session, mock.Mock(), mock.Mock())
        fake_objects = vmwareapi_fake.FakeRetrieveResult()
        for x in range(0, 3):
            vm = vmwareapi_fake.VirtualMachine()
            vm.set('config.extraConfig["nvp.vm-uuid"]',
                   vmwareapi_fake.OptionValue(
                       value=uuidutils.generate_uuid()))
            fake_objects.add_object(vm)
        vms = ops._get_valid_vms_from_retrieve_result(fake_objects)
        self.assertEqual(3, len(vms))

    def test_get_valid_vms_from_retrieve_result_with_invalid(self):
        ops = vmops.VMwareVMOps(self._session, mock.Mock(), mock.Mock())
        fake_objects = vmwareapi_fake.FakeRetrieveResult()
        valid_vm = vmwareapi_fake.VirtualMachine()
        valid_vm.set('config.extraConfig["nvp.vm-uuid"]',
                     vmwareapi_fake.OptionValue(
                         value=uuidutils.generate_uuid()))
        fake_objects.add_object(valid_vm)
        invalid_vm1 = vmwareapi_fake.VirtualMachine()
        invalid_vm1.set('runtime.connectionState', 'orphaned')
        invalid_vm1.set('config.extraConfig["nvp.vm-uuid"]',
                        vmwareapi_fake.OptionValue(
                            value=uuidutils.generate_uuid()))
        invalid_vm2 = vmwareapi_fake.VirtualMachine()
        invalid_vm2.set('runtime.connectionState', 'inaccessible')
        invalid_vm2.set('config.extraConfig["nvp.vm-uuid"]',
                        vmwareapi_fake.OptionValue(
                            value=uuidutils.generate_uuid()))
        fake_objects.add_object(invalid_vm1)
        fake_objects.add_object(invalid_vm2)
        vms = ops._get_valid_vms_from_retrieve_result(fake_objects)
        self.assertEqual(1, len(vms))

    def test_delete_vm_snapshot(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('RemoveSnapshot_Task', method)
            self.assertEqual('fake_vm_snapshot', args[0])
            self.assertFalse(kwargs['removeChildren'])
            self.assertTrue(kwargs['consolidate'])
            return 'fake_remove_snapshot_task'

        with test.nested(
            mock.patch.object(self._session, '_wait_for_task'),
            mock.patch.object(self._session, '_call_method', fake_call_method)
        ) as (_wait_for_task, _call_method):
            self._vmops._delete_vm_snapshot(self._instance,
                                            "fake_vm_ref", "fake_vm_snapshot")
            _wait_for_task.assert_has_calls([
                   mock.call('fake_remove_snapshot_task')])

    def test_create_vm_snapshot(self):

        method_list = ['CreateSnapshot_Task', 'get_object_property']

        def fake_call_method(module, method, *args, **kwargs):
            expected_method = method_list.pop(0)
            self.assertEqual(expected_method, method)
            if (expected_method == 'CreateSnapshot_Task'):
                self.assertEqual('fake_vm_ref', args[0])
                self.assertFalse(kwargs['memory'])
                self.assertTrue(kwargs['quiesce'])
                return 'fake_snapshot_task'
            elif (expected_method == 'get_object_property'):
                task_info = mock.Mock()
                task_info.result = "fake_snapshot_ref"
                self.assertEqual(('fake_snapshot_task', 'info'), args)
                return task_info

        with test.nested(
            mock.patch.object(self._session, '_wait_for_task'),
            mock.patch.object(self._session, '_call_method', fake_call_method)
        ) as (_wait_for_task, _call_method):
            snap = self._vmops._create_vm_snapshot(self._instance,
                                                   "fake_vm_ref")
            self.assertEqual("fake_snapshot_ref", snap)
            _wait_for_task.assert_has_calls([
                   mock.call('fake_snapshot_task')])

    def test_update_instance_progress(self):
        with mock.patch.object(self._instance, 'save') as mock_save:
            self._vmops._update_instance_progress(self._instance._context,
                                                  self._instance, 5, 10)
            mock_save.assert_called_once_with()
        self.assertEqual(50, self._instance.progress)

    @mock.patch.object(vm_util, 'get_vm_ref',
        return_value=vmwareapi_fake.ManagedObjectReference(value='test_id'))
    @mock.patch.object(vmops.VMwareVMOps, 'update_cached_instances')
    @mock.patch.object(vm_util, '_VM_VALUE_CACHE')
    def test_get_info(self, mock_value_cache,
                      mock_update_cached_instances, mock_get_vm_ref):
        result = {
            'summary.config.numCpu': 4,
            'summary.config.memorySizeMB': 128,
            'runtime.powerState': 'poweredOn'
        }

        with mock.patch.object(self._session, '_call_method',
                               return_value=result):
            info = self._vmops.get_info(self._instance)
            mock_get_vm_ref.assert_called_once_with(self._session,
                self._instance)
            expected = hardware.InstanceInfo(state=power_state.RUNNING)
            self.assertEqual(expected, info)

    @mock.patch.object(vm_util, 'get_vm_ref',
        return_value=vmwareapi_fake.ManagedObjectReference(
            value='fake_powered_off'))
    def test_get_info_when_ds_unavailable(self, mock_get_vm_ref):
        result = {
            'runtime.powerState': 'poweredOff'
        }

        with mock.patch.object(self._session, '_call_method',
                               return_value=result):
            info = self._vmops.get_info(self._instance)
            mock_get_vm_ref.assert_called_once_with(self._session,
                self._instance)
            self.assertEqual(hardware.InstanceInfo(state=power_state.SHUTDOWN),
                             info)

    @mock.patch.object(vm_util, 'get_vm_ref',
        return_value=vmwareapi_fake.ManagedObjectReference(
            value='fake_powered_off'))
    @mock.patch.object(vmops.VMwareVMOps, 'update_cached_instances')
    @mock.patch.object(vm_util, '_VM_VALUE_CACHE')
    def test_get_info_instance_deleted(self, mock_value_cache,
                                       mock_update_cached_instances,
                                       mock_get_vm_ref):
        vm_util.vm_value_cache_reset()
        props = ['summary.config.numCpu', 'summary.config.memorySizeMB',
                 'runtime.powerState']
        prop_cpu = vmwareapi_fake.Prop(props[0], 4)
        prop_mem = vmwareapi_fake.Prop(props[1], 128)
        prop_state = vmwareapi_fake.Prop(props[2], 'poweredOn')
        prop_list = [prop_state, prop_mem, prop_cpu]
        obj_content = vmwareapi_fake.ObjectContent(None, prop_list=prop_list)
        result = vmwareapi_fake.FakeRetrieveResult()
        result.add_object(obj_content)

        def mock_call_method(module, method, *args, **kwargs):
            raise vexc.ManagedObjectNotFoundException()

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            self.assertRaises(exception.InstanceNotFound,
                              self._vmops.get_info,
                              self._instance)
            mock_get_vm_ref.assert_called_once_with(self._session,
                self._instance)

    def _test_get_datacenter_ref_and_name(self, ds_ref_exists=False):
        instance_ds_ref = vmwareapi_fake.ManagedObjectReference(value='ds-1')
        _vcvmops = vmops.VMwareVMOps(self._session, None, None)
        result = vmwareapi_fake.FakeRetrieveResult()
        if ds_ref_exists:
            ds_ref = vmwareapi_fake.ManagedObjectReference(value='ds-1')
            result.add_object(vmwareapi_fake.Datacenter(ds_ref=ds_ref))
        else:
            result.add_object(vmwareapi_fake.Datacenter(ds_ref=None))
            result.add_object(vmwareapi_fake.Datacenter())

        with mock.patch.object(self._session, '_call_method',
                               return_value=result) as fake_call:
            dc_info = _vcvmops.get_datacenter_ref_and_name(instance_ds_ref)

            fake_call.assert_called_once_with(
                vim_util, "get_objects", "Datacenter",
                ["name", "datastore", "vmFolder"])
            if ds_ref_exists:
                self.assertEqual(1, len(ds_util._DS_DC_MAPPING))
                self.assertEqual("ha-datacenter", dc_info.name)
            else:
                self.assertIsNone(dc_info)

    def test_get_datacenter_ref_and_name(self):
        self._test_get_datacenter_ref_and_name(ds_ref_exists=True)

    def test_get_datacenter_ref_and_name_with_no_datastore(self):
        self._test_get_datacenter_ref_and_name()

    @mock.patch('nova.image.glance.API.get')
    @mock.patch.object(vm_util, 'power_off_instance')
    @mock.patch.object(ds_util, 'disk_copy')
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    @mock.patch.object(vm_util, 'find_rescue_device')
    @mock.patch.object(vm_util, 'get_vm_boot_spec')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'power_on_instance')
    @mock.patch.object(ds_obj, 'get_datastore_by_ref')
    def test_rescue(self, mock_get_ds_by_ref, mock_power_on, mock_reconfigure,
                    mock_get_boot_spec, mock_find_rescue,
                    mock_get_vm_ref, mock_disk_copy,
                    mock_power_off, mock_glance):
        _volumeops = mock.Mock()
        self._vmops._volumeops = _volumeops
        ds_ref = vmwareapi_fake.ManagedObjectReference(value='fake-ref')
        ds = ds_obj.Datastore(ds_ref, 'ds1')
        mock_get_ds_by_ref.return_value = ds
        mock_find_rescue.return_value = 'fake-rescue-device'
        mock_get_boot_spec.return_value = 'fake-boot-spec'
        vm_ref = vmwareapi_fake.ManagedObjectReference()
        mock_get_vm_ref.return_value = vm_ref

        device = vmwareapi_fake.DataObject()
        backing = vmwareapi_fake.DataObject()
        backing.datastore = ds.ref
        device.backing = backing
        vmdk = vm_util.VmdkInfo('[fake] test (uuid)/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                'fake-capacity',
                                device)

        with test.nested(
            mock.patch.object(self._vmops, 'get_datacenter_ref_and_name'),
            mock.patch.object(vm_util, 'get_vmdk_info',
                              return_value=vmdk)
        ) as (_get_dc_ref_and_name, fake_vmdk_info):
            dc_info = mock.Mock()
            _get_dc_ref_and_name.return_value = dc_info
            self._vmops.rescue(
                self._context, self._instance, None, self._image_meta)
            mock_power_off.assert_called_once_with(self._session,
                                                   self._instance,
                                                   vm_ref)

            uuid = self._instance.image_ref
            cache_path = ds.build_path('vmware_base', uuid, uuid + '.vmdk')
            vm_folder = ds_obj.DatastorePath.parse(vmdk.path).dirname
            rescue_path = ds.build_path(vm_folder, uuid + '-rescue.vmdk')

            mock_disk_copy.assert_called_once_with(self._session, dc_info.ref,
                             cache_path, rescue_path)
            _volumeops.attach_disk_to_vm.assert_called_once_with(vm_ref,
                             self._instance, mock.ANY, mock.ANY, rescue_path)
            mock_get_boot_spec.assert_called_once_with(mock.ANY,
                                                       'fake-rescue-device')
            mock_reconfigure.assert_called_once_with(self._session,
                                                     vm_ref,
                                                     'fake-boot-spec')
            mock_power_on.assert_called_once_with(self._session,
                                                  self._instance,
                                                  vm_ref=vm_ref)

    def test_unrescue_power_on(self):
        self._test_unrescue(True)

    def test_unrescue_power_off(self):
        self._test_unrescue(False)

    def _test_unrescue(self, power_on):
        _volumeops = mock.Mock()
        self._vmops._volumeops = _volumeops
        vm_ref = mock.Mock()

        def fake_call_method(module, method, *args, **kwargs):
            expected_args = (vm_ref, 'config.hardware.device')
            self.assertEqual('get_object_property', method)
            self.assertEqual(expected_args, args)

        with test.nested(
                mock.patch.object(vm_util, 'power_on_instance'),
                mock.patch.object(vm_util, 'find_rescue_device'),
                mock.patch.object(vm_util, 'get_vm_ref', return_value=vm_ref),
                mock.patch.object(self._session, '_call_method',
                                  fake_call_method),
                mock.patch.object(vm_util, 'power_off_instance')
        ) as (_power_on_instance, _find_rescue, _get_vm_ref,
              _call_method, _power_off):
            self._vmops.unrescue(self._instance, power_on=power_on)

            if power_on:
                _power_on_instance.assert_called_once_with(self._session,
                        self._instance, vm_ref=vm_ref)
            else:
                self.assertFalse(_power_on_instance.called)
            _get_vm_ref.assert_called_once_with(self._session,
                                                self._instance)
            _power_off.assert_called_once_with(self._session, self._instance,
                                               vm_ref)
            _volumeops.detach_disk_from_vm.assert_called_once_with(
                vm_ref, self._instance, mock.ANY, destroy_disk=True)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(vmops.VMwareVMOps, 'update_cached_instances')
    def _test_clean_shutdown(self, mock_update_cached_instances,
                             mock_sleep,
                             timeout, retry_interval,
                             returns_on, returns_off,
                             vmware_tools_status,
                             succeeds):
        """Test the _clean_shutdown method

        :param timeout: timeout before soft shutdown is considered a fail
        :param retry_interval: time between rechecking instance power state
        :param returns_on: how often the instance is reported as poweredOn
        :param returns_off: how often the instance is reported as poweredOff
        :param vmware_tools_status: Status of vmware tools
        :param succeeds: the expected result
        """
        instance = self._instance
        vm_ref = mock.Mock()
        return_props = []
        expected_methods = ['get_object_properties_dict']
        props_on = {'runtime.powerState': 'poweredOn',
                   'summary.guest.toolsStatus': vmware_tools_status,
                   'summary.guest.toolsRunningStatus': 'guestToolsRunning'}
        props_off = {'runtime.powerState': 'poweredOff',
                    'summary.guest.toolsStatus': vmware_tools_status,
                    'summary.guest.toolsRunningStatus': 'guestToolsRunning'}

        # initialize expected instance methods and returned properties
        if vmware_tools_status == "toolsOk":
            if returns_on > 0:
                expected_methods.append('ShutdownGuest')
                for x in range(returns_on + 1):
                    return_props.append(props_on)
                for x in range(returns_on):
                    expected_methods.append('get_object_properties_dict')
            for x in range(returns_off):
                return_props.append(props_off)
                if returns_on > 0:
                    expected_methods.append('get_object_properties_dict')
        else:
            return_props.append(props_off)

        def fake_call_method(module, method, *args, **kwargs):
            expected_method = expected_methods.pop(0)
            self.assertEqual(expected_method, method)
            if expected_method == 'get_object_properties_dict':
                props = return_props.pop(0)
                return props
            elif expected_method == 'ShutdownGuest':
                return

        with test.nested(
                mock.patch.object(vm_util, 'get_vm_ref', return_value=vm_ref),
                mock.patch.object(self._session, '_call_method',
                                  side_effect=fake_call_method)
        ) as (mock_get_vm_ref, mock_call_method):
            result = self._vmops._clean_shutdown(instance, timeout,
                                                 retry_interval)

        self.assertEqual(succeeds, result)
        mock_get_vm_ref.assert_called_once_with(self._session,
                                                self._instance)

    def test_clean_shutdown_first_time(self):
        self._test_clean_shutdown(timeout=10,
                                  retry_interval=3,
                                  returns_on=1,
                                  returns_off=1,
                                  vmware_tools_status="toolsOk",
                                  succeeds=True)

    def test_clean_shutdown_second_time(self):
        self._test_clean_shutdown(timeout=10,
                                  retry_interval=3,
                                  returns_on=2,
                                  returns_off=1,
                                  vmware_tools_status="toolsOk",
                                  succeeds=True)

    def test_clean_shutdown_timeout(self):
        self._test_clean_shutdown(timeout=10,
                                  retry_interval=3,
                                  returns_on=4,
                                  returns_off=0,
                                  vmware_tools_status="toolsOk",
                                  succeeds=False)

    def test_clean_shutdown_already_off(self):
        self._test_clean_shutdown(timeout=10,
                                  retry_interval=3,
                                  returns_on=0,
                                  returns_off=1,
                                  vmware_tools_status="toolsOk",
                                  succeeds=False)

    def test_clean_shutdown_no_vwaretools(self):
        self._test_clean_shutdown(timeout=10,
                                  retry_interval=3,
                                  returns_on=1,
                                  returns_off=0,
                                  vmware_tools_status="toolsNotOk",
                                  succeeds=False)

    def _test_finish_migration(self, power_on=True, resize_instance=False):
        with test.nested(
                mock.patch.object(self._vmops,
                                  '_resize_create_ephemerals_and_swap'),
                mock.patch.object(self._vmops, "_update_instance_progress"),
                mock.patch.object(vm_util, "power_on_instance"),
                mock.patch.object(vm_util, "get_vm_ref",
                                  return_value='fake-ref')
        ) as (fake_resize_create_ephemerals_and_swap,
              fake_update_instance_progress, fake_power_on, fake_get_vm_ref):
            self._vmops.finish_migration(context=self._context,
                                         migration=None,
                                         instance=self._instance,
                                         disk_info=None,
                                         network_info=None,
                                         block_device_info=None,
                                         resize_instance=resize_instance,
                                         image_meta=None,
                                         power_on=power_on)
            fake_resize_create_ephemerals_and_swap.assert_called_once_with(
                'fake-ref', self._instance, None)
            if power_on:
                fake_power_on.assert_called_once_with(self._session,
                                                      self._instance,
                                                      vm_ref='fake-ref')
            else:
                self.assertFalse(fake_power_on.called)

        calls = [
                mock.call(self._context, self._instance, step=5,
                          total_steps=vmops.RESIZE_TOTAL_STEPS),
                mock.call(self._context, self._instance, step=6,
                          total_steps=vmops.RESIZE_TOTAL_STEPS)]
        fake_update_instance_progress.assert_has_calls(calls)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(power_on=True, resize_instance=False)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(power_on=False, resize_instance=False)

    def test_finish_migration_power_on_resize(self):
        self._test_finish_migration(power_on=True, resize_instance=True)

    @mock.patch.object(vmops.VMwareVMOps, '_create_swap')
    @mock.patch.object(vmops.VMwareVMOps, '_create_ephemeral')
    @mock.patch.object(ds_obj, 'get_datastore_by_ref',
                       return_value='fake-ds-ref')
    @mock.patch.object(vm_util, 'get_vmdk_info')
    def _test_resize_create_ephemerals(self, vmdk, datastore,
                                       mock_get_vmdk_info,
                                       mock_get_datastore_by_ref,
                                       mock_create_ephemeral,
                                       mock_create_swap):
        mock_get_vmdk_info.return_value = vmdk
        dc_info = ds_util.DcInfo(ref='fake_ref', name='fake',
                                 vmFolder='fake_folder')
        with mock.patch.object(self._vmops, 'get_datacenter_ref_and_name',
            return_value=dc_info) as mock_get_dc_ref_and_name:
            self._vmops._resize_create_ephemerals_and_swap(
                'vm-ref', self._instance, 'block-devices')
            mock_get_vmdk_info.assert_called_once_with(
                self._session, 'vm-ref', uuid=self._instance.uuid)
            if vmdk.device:
                mock_get_datastore_by_ref.assert_called_once_with(
                    self._session, datastore.ref)
                mock_get_dc_ref_and_name.assert_called_once_with(datastore.ref)
                mock_create_ephemeral.assert_called_once_with(
                    'block-devices', self._instance, 'vm-ref',
                    dc_info, 'fake-ds-ref', 'uuid', 'fake-adapter')
                mock_create_swap.assert_called_once_with(
                    'block-devices', self._instance, 'vm-ref',
                    dc_info, 'fake-ds-ref', 'uuid', 'fake-adapter')
            else:
                self.assertFalse(mock_create_ephemeral.called)
                self.assertFalse(mock_get_dc_ref_and_name.called)
                self.assertFalse(mock_get_datastore_by_ref.called)

    def test_resize_create_ephemerals(self):
        datastore = ds_obj.Datastore(ref='fake-ref', name='fake')
        device = vmwareapi_fake.DataObject()
        backing = vmwareapi_fake.DataObject()
        backing.datastore = datastore.ref
        device.backing = backing
        vmdk = vm_util.VmdkInfo('[fake] uuid/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                'fake-capacity',
                                device)
        self._test_resize_create_ephemerals(vmdk, datastore)

    def test_resize_create_ephemerals_no_root(self):
        vmdk = vm_util.VmdkInfo(None, None, None, 0, None)
        self._test_resize_create_ephemerals(vmdk, None)

    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(vmops.VMwareVMOps, '_resize_create_ephemerals_and_swap')
    @mock.patch.object(vmops.VMwareVMOps, '_remove_ephemerals_and_swap')
    @mock.patch.object(ds_util, 'disk_delete')
    @mock.patch.object(ds_util, 'disk_move')
    @mock.patch.object(ds_util, 'file_exists',
                       return_value=True)
    @mock.patch.object(vmops.VMwareVMOps, '_get_ds_browser',
                       return_value='fake-browser')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'get_vm_resize_spec',
                       return_value='fake-spec')
    @mock.patch.object(vm_util, 'power_off_instance')
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    @mock.patch.object(vm_util, 'power_on_instance')
    def _test_finish_revert_migration(self, fake_power_on,
                                      fake_get_vm_ref, fake_power_off,
                                      fake_resize_spec, fake_reconfigure_vm,
                                      fake_get_browser,
                                      fake_original_exists, fake_disk_move,
                                      fake_disk_delete,
                                      fake_remove_ephemerals_and_swap,
                                      fake_resize_create_ephemerals_and_swap,
                                      fake_get_extra_specs,
                                      power_on):
        """Tests the finish_revert_migration method on vmops."""
        datastore = ds_obj.Datastore(ref='fake-ref', name='fake')
        device = vmwareapi_fake.DataObject()
        backing = vmwareapi_fake.DataObject()
        backing.datastore = datastore.ref
        device.backing = backing
        vmdk = vm_util.VmdkInfo('[fake] uuid/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                'fake-capacity',
                                device)
        dc_info = ds_util.DcInfo(ref='fake_ref', name='fake',
                                 vmFolder='fake_folder')
        extra_specs = vm_util.ExtraSpecs()
        fake_get_extra_specs.return_value = extra_specs
        with test.nested(
            mock.patch.object(self._vmops, 'get_datacenter_ref_and_name',
                              return_value=dc_info),
            mock.patch.object(vm_util, 'get_vmdk_info',
                              return_value=vmdk)
        ) as (fake_get_dc_ref_and_name, fake_get_vmdk_info):
            self._vmops._volumeops = mock.Mock()
            mock_attach_disk = self._vmops._volumeops.attach_disk_to_vm
            mock_detach_disk = self._vmops._volumeops.detach_disk_from_vm

            self._vmops.finish_revert_migration(self._context,
                                                instance=self._instance,
                                                network_info=None,
                                                block_device_info=None,
                                                power_on=power_on)
            fake_get_vm_ref.assert_called_once_with(self._session,
                                                    self._instance)
            fake_power_off.assert_called_once_with(self._session,
                                                   self._instance,
                                                   'fake-ref')
            # Validate VM reconfiguration
            metadata = ('name:fake_display_name\n'
                        'userid:fake_user\n'
                        'username:None\n'
                        'projectid:fake_project\n'
                        'projectname:None\n'
                        'flavor:name:m1.small\n'
                        'flavor:memory_mb:512\n'
                        'flavor:vcpus:1\n'
                        'flavor:ephemeral_gb:0\n'
                        'flavor:root_gb:10\n'
                        'flavor:swap:0\n'
                        'imageid:%s\n'
                        'package:%s\n' % (
                            uuids.image,
                            version.version_string_with_package()))
            fake_resize_spec.assert_called_once_with(
                self._session.vim.client.factory,
                int(self._instance.vcpus),
                int(self._instance.memory_mb),
                extra_specs,
                metadata=metadata)
            fake_reconfigure_vm.assert_called_once_with(self._session,
                                                        'fake-ref',
                                                        'fake-spec')
            # Validate disk configuration
            fake_get_vmdk_info.assert_called_once_with(
                self._session, 'fake-ref', uuid=self._instance.uuid)
            fake_get_browser.assert_called_once_with('fake-ref')
            fake_original_exists.assert_called_once_with(
                 self._session, 'fake-browser',
                 ds_obj.DatastorePath(datastore.name, 'uuid'),
                 'original.vmdk')

            mock_detach_disk.assert_called_once_with('fake-ref',
                                                     self._instance,
                                                     device)
            fake_disk_delete.assert_called_once_with(
                self._session, dc_info.ref, '[fake] uuid/root.vmdk')
            fake_disk_move.assert_called_once_with(
                self._session, dc_info.ref,
                '[fake] uuid/original.vmdk',
                '[fake] uuid/root.vmdk')
            mock_attach_disk.assert_called_once_with(
                    'fake-ref', self._instance, 'fake-adapter', 'fake-disk',
                    '[fake] uuid/root.vmdk',
                    disk_io_limits=extra_specs.disk_io_limits)
            fake_remove_ephemerals_and_swap.assert_called_once_with('fake-ref')
            fake_resize_create_ephemerals_and_swap.assert_called_once_with(
                'fake-ref', self._instance, None)
        if power_on:
            fake_power_on.assert_called_once_with(self._session,
                                                  self._instance)
        else:
            self.assertFalse(fake_power_on.called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(power_on=True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(power_on=False)

    def _test_find_esx_host(self, cluster_hosts, ds_hosts):
        def mock_call_method(module, method, *args, **kwargs):
            if args[0] == 'fake_cluster':
                ret = mock.MagicMock()
                ret.ManagedObjectReference = cluster_hosts
                return ret
            elif args[0] == 'fake_ds':
                ret = mock.MagicMock()
                ret.DatastoreHostMount = ds_hosts
                return ret

        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            return self._vmops._find_esx_host('fake_cluster', 'fake_ds')

    def test_find_esx_host(self):
        ch1 = vmwareapi_fake.ManagedObjectReference(value='host-10')
        ch2 = vmwareapi_fake.ManagedObjectReference(value='host-12')
        ch3 = vmwareapi_fake.ManagedObjectReference(value='host-15')
        dh1 = vmwareapi_fake.DatastoreHostMount('host-8')
        dh2 = vmwareapi_fake.DatastoreHostMount('host-12')
        dh3 = vmwareapi_fake.DatastoreHostMount('host-17')
        ret = self._test_find_esx_host([ch1, ch2, ch3], [dh1, dh2, dh3])
        self.assertEqual('host-12', ret.value)

    def test_find_esx_host_none(self):
        ch1 = vmwareapi_fake.ManagedObjectReference(value='host-10')
        ch2 = vmwareapi_fake.ManagedObjectReference(value='host-12')
        ch3 = vmwareapi_fake.ManagedObjectReference(value='host-15')
        dh1 = vmwareapi_fake.DatastoreHostMount('host-8')
        dh2 = vmwareapi_fake.DatastoreHostMount('host-13')
        dh3 = vmwareapi_fake.DatastoreHostMount('host-17')
        ret = self._test_find_esx_host([ch1, ch2, ch3], [dh1, dh2, dh3])
        self.assertIsNone(ret)

    @mock.patch.object(vm_util, 'get_vmdk_info')
    @mock.patch.object(ds_obj, 'get_datastore_by_ref')
    def test_find_datastore_for_migration(self, mock_get_ds, mock_get_vmdk):
        def mock_call_method(module, method, *args, **kwargs):
            ds1 = vmwareapi_fake.ManagedObjectReference(value='datastore-10')
            ds2 = vmwareapi_fake.ManagedObjectReference(value='datastore-12')
            ds3 = vmwareapi_fake.ManagedObjectReference(value='datastore-15')
            ret = mock.MagicMock()
            ret.ManagedObjectReference = [ds1, ds2, ds3]
            return ret
        ds_ref = vmwareapi_fake.ManagedObjectReference(value='datastore-12')
        vmdk_dev = mock.MagicMock()
        vmdk_dev.device.backing.datastore = ds_ref
        mock_get_vmdk.return_value = vmdk_dev
        ds = ds_obj.Datastore(ds_ref, 'datastore1')
        mock_get_ds.return_value = ds
        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            ret = self._vmops._find_datastore_for_migration(self._instance,
                                                   'fake_vm', 'cluster_ref',
                                                   None)
            self.assertIs(ds, ret)
            mock_get_vmdk.assert_called_once_with(self._session, 'fake_vm',
                                                  uuid=self._instance.uuid)
            mock_get_ds.assert_called_once_with(self._session, ds_ref)

    @mock.patch.object(vm_util, 'get_vmdk_info')
    @mock.patch.object(ds_util, 'get_datastore')
    def test_find_datastore_for_migration_other(self, mock_get_ds,
                                                mock_get_vmdk):
        def mock_call_method(module, method, *args, **kwargs):
            ds1 = vmwareapi_fake.ManagedObjectReference(value='datastore-10')
            ds2 = vmwareapi_fake.ManagedObjectReference(value='datastore-12')
            ds3 = vmwareapi_fake.ManagedObjectReference(value='datastore-15')
            ret = mock.MagicMock()
            ret.ManagedObjectReference = [ds1, ds2, ds3]
            return ret
        ds_ref = vmwareapi_fake.ManagedObjectReference(value='datastore-18')
        vmdk_dev = mock.MagicMock()
        vmdk_dev.device.backing.datastore = ds_ref
        mock_get_vmdk.return_value = vmdk_dev
        ds = ds_obj.Datastore(ds_ref, 'datastore1')
        mock_get_ds.return_value = ds
        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            ret = self._vmops._find_datastore_for_migration(self._instance,
                                                   'fake_vm', 'cluster_ref',
                                                   None)
            self.assertIs(ds, ret)
            mock_get_vmdk.assert_called_once_with(self._session, 'fake_vm',
                                                  uuid=self._instance.uuid)
            mock_get_ds.assert_called_once_with(self._session, 'cluster_ref',
                                                None)

    @mock.patch.object(vm_util, 'relocate_vm')
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake_vm')
    @mock.patch.object(vm_util, 'get_cluster_ref_by_name',
                       return_value='fake_cluster')
    @mock.patch.object(vm_util, 'get_res_pool_ref', return_value='fake_pool')
    @mock.patch.object(vmops.VMwareVMOps, '_find_datastore_for_migration')
    @mock.patch.object(vmops.VMwareVMOps, '_find_esx_host',
                       return_value='fake_host')
    def test_live_migration(self, mock_find_host, mock_find_datastore,
                            mock_get_respool, mock_get_cluster, mock_get_vm,
                            mock_relocate):
        post_method = mock.MagicMock()
        migrate_data = objects.VMwareLiveMigrateData()
        migrate_data.cluster_name = 'fake-cluster'
        migrate_data.datastore_regex = 'ds1|ds2'
        mock_find_datastore.return_value = ds_obj.Datastore('ds_ref', 'ds')
        with mock.patch.object(self._session, '_call_method',
                               return_value='hardware-devices'):
            self._vmops.live_migration(
                self._context, self._instance, 'fake-host',
                post_method, None, False, migrate_data)
        mock_get_vm.assert_called_once_with(self._session, self._instance)
        mock_get_cluster.assert_called_once_with(self._session, 'fake-cluster')
        mock_find_datastore.assert_called_once_with(self._instance, 'fake_vm',
                                                    'fake_cluster', mock.ANY)
        mock_find_host.assert_called_once_with('fake_cluster', 'ds_ref')
        mock_relocate.assert_called_once_with(self._session, 'fake_vm',
                                    'fake_pool', 'ds_ref', 'fake_host',
                                    devices=[])
        post_method.assert_called_once_with(self._context, self._instance,
                                            'fake-host', False, migrate_data)

    @mock.patch.object(vmops.VMwareVMOps, '_get_instance_metadata')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'get_vm_resize_spec',
                       return_value='fake-spec')
    def test_resize_vm(self, fake_resize_spec, fake_reconfigure,
                       fake_get_extra_specs, fake_get_metadata):
        extra_specs = vm_util.ExtraSpecs()
        fake_get_extra_specs.return_value = extra_specs
        fake_get_metadata.return_value = self._metadata
        flavor = objects.Flavor(name='m1.small',
                                memory_mb=1024,
                                vcpus=2,
                                extra_specs={})
        self._vmops._resize_vm(self._context, self._instance, 'vm-ref', flavor,
                               None)
        fake_get_metadata.assert_called_once_with(self._context,
                                                  self._instance,
                                                  flavor=flavor)
        fake_resize_spec.assert_called_once_with(
            self._session.vim.client.factory, 2, 1024, extra_specs,
                metadata=self._metadata)
        fake_reconfigure.assert_called_once_with(self._session,
                                                 'vm-ref', 'fake-spec')

    @mock.patch.object(vmops.VMwareVMOps, '_extend_virtual_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(ds_util, 'disk_move')
    @mock.patch.object(ds_util, 'disk_copy')
    def test_resize_disk(self, fake_disk_copy, fake_disk_move,
                         fake_get_extra_specs, fake_extend):
        datastore = ds_obj.Datastore(ref='fake-ref', name='fake')
        device = vmwareapi_fake.DataObject()
        backing = vmwareapi_fake.DataObject()
        backing.datastore = datastore.ref
        device.backing = backing
        vmdk = vm_util.VmdkInfo('[fake] uuid/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                self._instance.flavor.root_gb * units.Gi,
                                device)
        dc_info = ds_util.DcInfo(ref='fake_ref', name='fake',
                                 vmFolder='fake_folder')
        with mock.patch.object(self._vmops, 'get_datacenter_ref_and_name',
            return_value=dc_info) as fake_get_dc_ref_and_name:
            self._vmops._volumeops = mock.Mock()
            mock_attach_disk = self._vmops._volumeops.attach_disk_to_vm
            mock_detach_disk = self._vmops._volumeops.detach_disk_from_vm

            extra_specs = vm_util.ExtraSpecs()
            fake_get_extra_specs.return_value = extra_specs
            flavor = fake_flavor.fake_flavor_obj(self._context,
                         root_gb=self._instance.flavor.root_gb + 1)
            self._vmops._resize_disk(self._instance, 'fake-ref', vmdk, flavor)
            fake_get_dc_ref_and_name.assert_called_once_with(datastore.ref)
            fake_disk_copy.assert_called_once_with(
                self._session, dc_info.ref, '[fake] uuid/root.vmdk',
                '[fake] uuid/resized.vmdk')
            mock_detach_disk.assert_called_once_with('fake-ref',
                                                     self._instance,
                                                     device)
            fake_extend.assert_called_once_with(
                self._instance, flavor['root_gb'] * units.Mi,
                '[fake] uuid/resized.vmdk', dc_info.ref)
            calls = [
                    mock.call(self._session, dc_info.ref,
                              '[fake] uuid/root.vmdk',
                              '[fake] uuid/original.vmdk'),
                    mock.call(self._session, dc_info.ref,
                              '[fake] uuid/resized.vmdk',
                              '[fake] uuid/root.vmdk')]
            fake_disk_move.assert_has_calls(calls)

            mock_attach_disk.assert_called_once_with(
                    'fake-ref', self._instance, 'fake-adapter', 'fake-disk',
                    '[fake] uuid/root.vmdk',
                    disk_io_limits=extra_specs.disk_io_limits)

    @mock.patch.object(vm_util, 'detach_devices_from_vm')
    @mock.patch.object(vm_util, 'get_swap')
    @mock.patch.object(vm_util, 'get_ephemerals')
    def test_remove_ephemerals_and_swap(self, get_ephemerals, get_swap,
                                        detach_devices):
        get_ephemerals.return_value = [mock.sentinel.ephemeral0,
                                       mock.sentinel.ephemeral1]
        get_swap.return_value = mock.sentinel.swap
        devices = [mock.sentinel.ephemeral0, mock.sentinel.ephemeral1,
                   mock.sentinel.swap]

        self._vmops._remove_ephemerals_and_swap(mock.sentinel.vm_ref)
        detach_devices.assert_called_once_with(self._vmops._session,
                                               mock.sentinel.vm_ref, devices)

    @mock.patch.object(ds_util, 'disk_delete')
    @mock.patch.object(ds_util, 'file_exists',
                       return_value=True)
    @mock.patch.object(vmops.VMwareVMOps, '_get_ds_browser',
                       return_value='fake-browser')
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def test_confirm_migration(self, fake_get_vm_ref, fake_get_browser,
                               fake_original_exists,
                               fake_disk_delete):
        """Tests the confirm_migration method on vmops."""
        datastore = ds_obj.Datastore(ref='fake-ref', name='fake')
        device = vmwareapi_fake.DataObject()
        backing = vmwareapi_fake.DataObject()
        backing.datastore = datastore.ref
        device.backing = backing
        vmdk = vm_util.VmdkInfo('[fake] uuid/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                'fake-capacity',
                                device)
        dc_info = ds_util.DcInfo(ref='fake_ref', name='fake',
                                 vmFolder='fake_folder')
        with test.nested(
            mock.patch.object(self._vmops, 'get_datacenter_ref_and_name',
                              return_value=dc_info),
            mock.patch.object(vm_util, 'get_vmdk_info',
                              return_value=vmdk)
        ) as (fake_get_dc_ref_and_name, fake_get_vmdk_info):
            self._vmops.confirm_migration(None,
                                          self._instance,
                                          None)
            fake_get_vm_ref.assert_called_once_with(self._session,
                                                    self._instance)
            fake_get_vmdk_info.assert_called_once_with(
                self._session, 'fake-ref', uuid=self._instance.uuid)
            fake_get_browser.assert_called_once_with('fake-ref')
            fake_original_exists.assert_called_once_with(
                self._session, 'fake-browser',
                ds_obj.DatastorePath(datastore.name, 'uuid'),
                'original.vmdk')
            fake_disk_delete.assert_called_once_with(
                self._session, dc_info.ref, '[fake] uuid/original.vmdk')

    def test_migrate_disk_and_power_off(self):
        self._test_migrate_disk_and_power_off(
            flavor_root_gb=self._instance.flavor.root_gb + 1)

    def test_migrate_disk_and_power_off_zero_disk_flavor(self):
        self._instance.flavor.root_gb = 0
        self._test_migrate_disk_and_power_off(flavor_root_gb=0)

    def test_migrate_disk_and_power_off_disk_shrink(self):
        self.assertRaises(exception.InstanceFaultRollback,
                          self._test_migrate_disk_and_power_off,
                          flavor_root_gb=self._instance.flavor.root_gb - 1)

    @mock.patch.object(vmops.VMwareVMOps, "_remove_ephemerals_and_swap")
    @mock.patch.object(vm_util, 'get_vmdk_info')
    @mock.patch.object(vmops.VMwareVMOps, "_resize_disk")
    @mock.patch.object(vmops.VMwareVMOps, "_resize_vm")
    @mock.patch.object(vm_util, 'power_off_instance')
    @mock.patch.object(vmops.VMwareVMOps, "_update_instance_progress")
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def _test_migrate_disk_and_power_off(self, fake_get_vm_ref, fake_progress,
                                         fake_power_off, fake_resize_vm,
                                         fake_resize_disk, fake_get_vmdk_info,
                                         fake_remove_ephemerals_and_swap,
                                         flavor_root_gb):
        vmdk = vm_util.VmdkInfo('[fake] uuid/root.vmdk',
                                'fake-adapter',
                                'fake-disk',
                                self._instance.flavor.root_gb * units.Gi,
                                'fake-device')
        fake_get_vmdk_info.return_value = vmdk
        flavor = fake_flavor.fake_flavor_obj(self._context,
                                             root_gb=flavor_root_gb)
        self._vmops.migrate_disk_and_power_off(self._context,
                                               self._instance,
                                               None,
                                               flavor)

        fake_get_vm_ref.assert_called_once_with(self._session,
                                                self._instance)

        fake_power_off.assert_called_once_with(self._session,
                                               self._instance,
                                               'fake-ref')
        fake_resize_vm.assert_called_once_with(self._context, self._instance,
                                               'fake-ref', flavor, mock.ANY)
        fake_resize_disk.assert_called_once_with(self._instance, 'fake-ref',
                                                 vmdk, flavor)
        calls = [mock.call(self._context, self._instance, step=i,
                           total_steps=vmops.RESIZE_TOTAL_STEPS)
                 for i in range(4)]
        fake_progress.assert_has_calls(calls)

    @mock.patch.object(vutil, 'get_inventory_path', return_value='fake_path')
    @mock.patch.object(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
    @mock.patch.object(vmops.VMwareVMOps, '_create_config_drive')
    def test_configure_config_drive(self,
                                    mock_create_config_drive,
                                    mock_attach_cdrom_to_vm,
                                    mock_get_inventory_path):
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = mock.Mock()
        vm_ref = mock.Mock()
        mock_create_config_drive.return_value = "fake_iso_path"
        self._vmops._configure_config_drive(
                self._context, self._instance, vm_ref, self._dc_info, self._ds,
                injected_files, admin_password, network_info)

        upload_iso_path = self._ds.build_path("fake_iso_path")
        mock_get_inventory_path.assert_called_once_with(self._session.vim,
                                                        self._dc_info.ref)
        mock_create_config_drive.assert_called_once_with(
                self._context, self._instance, injected_files, admin_password,
                network_info, self._ds.name, 'fake_path', self._instance.uuid,
                "Fake-CookieJar")
        mock_attach_cdrom_to_vm.assert_called_once_with(
                vm_ref, self._instance, self._ds.ref, str(upload_iso_path))

    @mock.patch('nova.image.glance.API.get')
    @mock.patch.object(vmops.LOG, 'debug')
    @mock.patch.object(vmops.VMwareVMOps, '_fetch_image_if_missing')
    @mock.patch.object(vmops.VMwareVMOps, '_get_vm_config_info')
    @mock.patch.object(vmops.VMwareVMOps, 'build_virtual_machine')
    @mock.patch.object(vmops.lockutils, 'lock')
    @mock.patch.object(ds_util, 'get_datastore')
    def test_spawn_mask_block_device_info_password(self, mock_get_datastore,
        mock_lock, mock_build_virtual_machine, mock_get_vm_config_info,
        mock_fetch_image_if_missing, mock_debug, mock_glance):
        # Very simple test that just ensures block_device_info auth_password
        # is masked when logged; the rest of the test just fails out early.
        data = {'auth_password': 'scrubme'}
        bdm = [{'boot_index': 0, 'disk_bus': constants.DEFAULT_ADAPTER_TYPE,
                'connection_info': {'data': data}}]
        bdi = {'block_device_mapping': bdm}
        mock_get_datastore.return_value = self._ds
        self.password_logged = False

        # Tests that the parameters to the to_xml method are sanitized for
        # passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.password_logged = True
                self.assertNotIn('scrubme', args[0])

        mock_debug.side_effect = fake_debug
        self.flags(flat_injected=False)
        self.flags(enabled=False, group='vnc')

        extra_specs = vm_util.ExtraSpecs()
        flavor_fits_image = False
        file_size = 10 * units.Gi if flavor_fits_image else 5 * units.Gi
        image_info = images.VMwareImage(
            image_id=self._image_id,
            file_size=file_size,
            linked_clone=False)

        cache_root_folder = self._ds.build_path("vmware_base", self._image_id)
        mock_imagecache = mock.Mock()
        mock_imagecache.get_image_cache_folder.return_value = cache_root_folder
        dc_info = ds_util.DcInfo(
            ref=self._cluster, name='fake_dc',
            vmFolder=vmwareapi_fake.ManagedObjectReference(
                name='Folder',
                value='fake_vm_folder'))
        vi = vmops.VirtualMachineInstanceConfigInfo(
            self._instance, image_info,
            self._ds, dc_info, mock_imagecache, extra_specs)
        mock_get_vm_config_info.return_value = vi

        # Call spawn(). We don't care what it does as long as it generates
        # the log message, which we check below.
        with mock.patch.object(self._vmops, '_volumeops') as mock_vo:
            mock_vo.attach_root_volume.side_effect = test.TestingException
            try:
                self._vmops.spawn(
                    self._context, self._instance, self._image_meta,
                    injected_files=None, admin_password=None,
                    network_info=[], block_device_info=bdi
                )
            except test.TestingException:
                pass

        # Check that the relevant log message was generated, and therefore
        # that we checked it was scrubbed
        self.assertTrue(self.password_logged)

    def _get_metadata(self, is_image_used=True):
        return ("name:fake_display_name\n"
                "userid:fake_user\n"
                "username:None\n"
                "projectid:fake_project\n"
                "projectname:None\n"
                "flavor:name:m1.small\n"
                "flavor:memory_mb:512\n"
                "flavor:vcpus:1\n"
                "flavor:ephemeral_gb:0\n"
                "flavor:root_gb:10\n"
                "flavor:swap:0\n"
                "imageid:%(image_id)s\n"
                "package:%(version)s\n" % {
                    'image_id': uuids.image if is_image_used else None,
                    'version': version.version_string_with_package()})

    @mock.patch.object(vm_util, 'rename_vm')
    @mock.patch.object(vmops.VMwareVMOps, '_create_folders',
                       return_value='fake_vm_folder')
    @mock.patch('nova.virt.vmwareapi.vm_util.power_on_instance')
    @mock.patch.object(vmops.VMwareVMOps, '_use_disk_image_as_linked_clone')
    @mock.patch.object(vmops.VMwareVMOps, '_fetch_image_if_missing')
    @mock.patch(
        'nova.virt.vmwareapi.imagecache.ImageCacheManager.enlist_image')
    @mock.patch.object(vmops.VMwareVMOps, 'build_virtual_machine')
    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch.object(vmops.VMwareVMOps, '_get_vm_config_info')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(images.VMwareImage, 'from_image')
    def test_spawn_non_root_block_device(self, from_image,
                                         get_extra_specs,
                                         get_vm_config_info,
                                         update_cluster_placement,
                                         build_virtual_machine,
                                         enlist_image, fetch_image,
                                         use_disk_image,
                                         power_on_instance,
                                         create_folders,
                                         rename_vm):
        self._instance.flavor = self._flavor
        extra_specs = get_extra_specs.return_value
        connection_info1 = {'data': 'fake-data1', 'serial': 'volume-fake-id1'}
        connection_info2 = {'data': 'fake-data2', 'serial': 'volume-fake-id2'}
        bdm = [{'connection_info': connection_info1,
                'disk_bus': constants.ADAPTER_TYPE_IDE,
                'mount_device': '/dev/sdb'},
               {'connection_info': connection_info2,
                'disk_bus': constants.DEFAULT_ADAPTER_TYPE,
                'mount_device': '/dev/sdc'}]
        bdi = {'block_device_mapping': bdm, 'root_device_name': '/dev/sda'}
        self.flags(flat_injected=False)
        self.flags(enabled=False, group='vnc')

        image_size = (self._instance.flavor.root_gb) * units.Gi / 2
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=image_size)
        vi = get_vm_config_info.return_value
        from_image.return_value = image_info
        build_virtual_machine.return_value = 'fake-vm-ref'
        with mock.patch.object(self._vmops, '_volumeops') as volumeops:
            self._vmops.spawn(self._context, self._instance, self._image_meta,
                              injected_files=None, admin_password=None,
                              network_info=[], block_device_info=bdi)

            from_image.assert_called_once_with(self._context,
                                               self._instance.image_ref,
                                               self._image_meta)
            get_vm_config_info.assert_called_once_with(self._instance,
                image_info, extra_specs)
            build_virtual_machine.assert_called_once_with(self._instance,
                                                          self._context,
                image_info, vi.dc_info, vi.datastore, [],
                extra_specs, self._get_metadata())
            enlist_image.assert_called_once_with(image_info.image_id,
                                                 vi.datastore, vi.dc_info.ref)
            fetch_image.assert_called_once_with(self._context, vi)
            use_disk_image.assert_called_once_with('fake-vm-ref', vi)
            volumeops.attach_volume.assert_any_call(
                connection_info1, self._instance, constants.ADAPTER_TYPE_IDE)
            volumeops.attach_volume.assert_any_call(
                connection_info2, self._instance,
                constants.DEFAULT_ADAPTER_TYPE)

    @mock.patch.object(vm_util, 'rename_vm')
    @mock.patch.object(vmops.VMwareVMOps, '_create_folders',
                       return_value='fake_vm_folder')
    @mock.patch('nova.virt.vmwareapi.vm_util.power_on_instance')
    @mock.patch.object(vmops.VMwareVMOps, 'build_virtual_machine')
    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch.object(vmops.VMwareVMOps, '_get_vm_config_info')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(images.VMwareImage, 'from_image')
    def test_spawn_with_no_image_and_block_devices(self, from_image,
                                                   get_extra_specs,
                                                   get_vm_config_info,
                                                   update_cluster_placement,
                                                   build_virtual_machine,
                                                   power_on_instance,
                                                   create_folders,
                                                   rename_vm):
        self._instance.image_ref = None
        self._instance.flavor = self._flavor
        extra_specs = get_extra_specs.return_value

        connection_info1 = {'data': 'fake-data1', 'serial': 'volume-fake-id1'}
        connection_info2 = {'data': 'fake-data2', 'serial': 'volume-fake-id2'}
        connection_info3 = {'data': 'fake-data3', 'serial': 'volume-fake-id3'}
        bdm = [{'boot_index': 0,
                'connection_info': connection_info1,
                'disk_bus': constants.ADAPTER_TYPE_IDE},
               {'boot_index': 1,
                'connection_info': connection_info2,
                'disk_bus': constants.DEFAULT_ADAPTER_TYPE},
               {'boot_index': 2,
                'connection_info': connection_info3,
                'disk_bus': constants.ADAPTER_TYPE_LSILOGICSAS}]
        bdi = {'block_device_mapping': bdm}
        self.flags(flat_injected=False)
        self.flags(enabled=False, group='vnc')

        image_info = mock.sentinel.image_info
        vi = get_vm_config_info.return_value
        from_image.return_value = image_info
        build_virtual_machine.return_value = 'fake-vm-ref'

        with mock.patch.object(self._vmops, '_volumeops') as volumeops:
            self._vmops.spawn(self._context, self._instance, self._image_meta,
                              injected_files=None, admin_password=None,
                              network_info=[], block_device_info=bdi)

            from_image.assert_called_once_with(self._context,
                                               self._instance.image_ref,
                                               self._image_meta)
            get_vm_config_info.assert_called_once_with(self._instance,
                image_info, extra_specs)
            build_virtual_machine.assert_called_once_with(self._instance,
                                                          self._context,
                image_info, vi.dc_info, vi.datastore, [],
                extra_specs, self._get_metadata(is_image_used=False))
            volumeops.attach_root_volume.assert_called_once_with(
                connection_info1, self._instance, vi.datastore.ref,
                constants.ADAPTER_TYPE_IDE)
            volumeops.attach_volume.assert_any_call(
                connection_info2, self._instance,
                constants.DEFAULT_ADAPTER_TYPE)
            volumeops.attach_volume.assert_any_call(
                connection_info3, self._instance,
                constants.ADAPTER_TYPE_LSILOGICSAS)

    @mock.patch.object(vmops.VMwareVMOps, '_create_folders',
                       return_value='fake_vm_folder')
    @mock.patch('nova.virt.vmwareapi.vm_util.power_on_instance')
    @mock.patch.object(vmops.VMwareVMOps, 'build_virtual_machine')
    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch.object(vmops.VMwareVMOps, '_get_vm_config_info')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(images.VMwareImage, 'from_image')
    def test_spawn_unsupported_hardware(self, from_image,
                                        get_extra_specs,
                                        get_vm_config_info,
                                        update_cluster_placement,
                                        build_virtual_machine,
                                        power_on_instance,
                                        create_folders):
        self._instance.image_ref = None
        self._instance.flavor = self._flavor
        extra_specs = get_extra_specs.return_value
        connection_info = {'data': 'fake-data', 'serial': 'volume-fake-id'}
        bdm = [{'boot_index': 0,
                'connection_info': connection_info,
                'disk_bus': 'invalid_adapter_type'}]
        bdi = {'block_device_mapping': bdm}
        self.flags(flat_injected=False)
        self.flags(enabled=False, group='vnc')

        image_info = mock.sentinel.image_info
        vi = get_vm_config_info.return_value
        from_image.return_value = image_info
        build_virtual_machine.return_value = 'fake-vm-ref'

        self.assertRaises(exception.UnsupportedHardware, self._vmops.spawn,
                          self._context, self._instance, self._image_meta,
                          injected_files=None,
                          admin_password=None, network_info=[],
                          block_device_info=bdi)

        from_image.assert_called_once_with(self._context,
                                           self._instance.image_ref,
                                           self._image_meta)
        get_vm_config_info.assert_called_once_with(
            self._instance, image_info, extra_specs)
        build_virtual_machine.assert_called_once_with(self._instance,
                                                      self._context,
            image_info, vi.dc_info, vi.datastore, [],
            extra_specs, self._get_metadata(is_image_used=False))

    def test_get_ds_browser(self):
        cache = self._vmops._datastore_browser_mapping
        ds_browser = mock.Mock()
        moref = vmwareapi_fake.ManagedObjectReference(value='datastore-100')
        self.assertIsNone(cache.get(moref.value))
        mock_call_method = mock.Mock(return_value=ds_browser)
        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            ret = self._vmops._get_ds_browser(moref)
            mock_call_method.assert_called_once_with(vutil,
                'get_object_property', moref, 'browser')
            self.assertIs(ds_browser, ret)
            self.assertIs(ds_browser, cache.get(moref.value))

    @mock.patch.object(
            vmops.VMwareVMOps, '_sized_image_exists', return_value=False)
    @mock.patch.object(vmops.VMwareVMOps, '_extend_virtual_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_extend_if_required')
    @mock.patch.object(vm_util, 'copy_virtual_disk')
    def _test_use_disk_image_as_linked_clone(self,
                                             mock_copy_virtual_disk,
                                             mock_extend_if_required,
                                             mock_extend_virtual_disk,
                                             mock_sized_image_exists,
                                             flavor_fits_image=False):
        extra_specs = vm_util.ExtraSpecs()
        file_size = 10 * units.Gi if flavor_fits_image else 5 * units.Gi
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=file_size,
                linked_clone=False)

        cache_root_folder = self._ds.build_path("vmware_base", self._image_id)
        mock_imagecache = mock.Mock()
        mock_imagecache.get_image_cache_folder.return_value = cache_root_folder
        vi = vmops.VirtualMachineInstanceConfigInfo(
                self._instance, image_info,
                self._ds, self._dc_info, mock_imagecache, extra_specs)

        sized_cached_image_ds_loc = cache_root_folder.join(
                "%s.%s.vmdk" % (self._image_id, vi.root_gb))

        self._vmops._volumeops = mock.Mock()
        mock_attach_disk_to_vm = self._vmops._volumeops.attach_disk_to_vm

        self._vmops._use_disk_image_as_linked_clone("fake_vm_ref", vi)

        mock_copy_virtual_disk.assert_called_once_with(
                self._session, self._dc_info.ref,
                str(vi.cache_image_path),
                str(sized_cached_image_ds_loc))

        mock_extend_if_required.assert_called_once_with(
            self._dc_info,
            vi.ii,
            vi.instance, str(sized_cached_image_ds_loc))

        mock_attach_disk_to_vm.assert_called_once_with(
                "fake_vm_ref", self._instance, vi.ii.adapter_type,
                vi.ii.disk_type,
                str(sized_cached_image_ds_loc),
                vi.root_gb * units.Mi, False,
                disk_io_limits=vi._extra_specs.disk_io_limits)

    def test_use_disk_image_as_linked_clone(self):
        self._test_use_disk_image_as_linked_clone()

    def test_use_disk_image_as_linked_clone_flavor_fits_image(self):
        self._test_use_disk_image_as_linked_clone(flavor_fits_image=True)

    @mock.patch.object(vmops.VMwareVMOps, '_extend_virtual_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_extend_if_required')
    @mock.patch.object(vm_util, 'copy_virtual_disk')
    def _test_use_disk_image_as_full_clone(self,
                                          mock_copy_virtual_disk,
                                          mock_extend_if_required,
                                          mock_extend_virtual_disk,
                                          flavor_fits_image=False):
        extra_specs = vm_util.ExtraSpecs()
        file_size = 10 * units.Gi if flavor_fits_image else 5 * units.Gi
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=file_size,
                linked_clone=False)

        cache_root_folder = self._ds.build_path("vmware_base", self._image_id)
        mock_imagecache = mock.Mock()
        mock_imagecache.get_image_cache_folder.return_value = cache_root_folder
        vi = vmops.VirtualMachineInstanceConfigInfo(
                self._instance, image_info,
                self._ds, self._dc_info, mock_imagecache,
                extra_specs)

        self._vmops._volumeops = mock.Mock()
        mock_attach_disk_to_vm = self._vmops._volumeops.attach_disk_to_vm

        self._vmops._use_disk_image_as_full_clone("fake_vm_ref", vi)

        fake_path = '[fake_ds] %(uuid)s/%(uuid)s.vmdk' % {'uuid': self._uuid}
        mock_copy_virtual_disk.assert_called_once_with(
                self._session, self._dc_info.ref,
                str(vi.cache_image_path),
                fake_path)

        mock_extend_if_required.assert_called_once_with(
            self._dc_info,
            vi.ii,
            vi.instance, fake_path)

        mock_attach_disk_to_vm.assert_called_once_with(
                "fake_vm_ref", self._instance, vi.ii.adapter_type,
                vi.ii.disk_type, fake_path,
                vi.root_gb * units.Mi, False,
                disk_io_limits=vi._extra_specs.disk_io_limits)

    def test_use_disk_image_as_full_clone(self):
        self._test_use_disk_image_as_full_clone()

    def test_use_disk_image_as_full_clone_image_too_big(self):
        self._test_use_disk_image_as_full_clone(flavor_fits_image=True)

    @mock.patch.object(vmops.VMwareVMOps, '_attach_cdrom_to_vm')
    @mock.patch.object(vm_util, 'create_virtual_disk')
    def _test_use_iso_image(self,
                            mock_create_virtual_disk,
                            mock_attach_cdrom,
                            with_root_disk):
        extra_specs = vm_util.ExtraSpecs()
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=10 * units.Mi,
                linked_clone=True)

        cache_root_folder = self._ds.build_path("vmware_base", self._image_id)
        mock_imagecache = mock.Mock()
        mock_imagecache.get_image_cache_folder.return_value = cache_root_folder
        vi = vmops.VirtualMachineInstanceConfigInfo(
                self._instance, image_info,
                self._ds, self._dc_info, mock_imagecache, extra_specs)

        self._vmops._volumeops = mock.Mock()
        mock_attach_disk_to_vm = self._vmops._volumeops.attach_disk_to_vm

        self._vmops._use_iso_image("fake_vm_ref", vi)

        mock_attach_cdrom.assert_called_once_with(
                "fake_vm_ref", self._instance, self._ds.ref,
                str(vi.cache_image_path))

        fake_path = '[fake_ds] %(uuid)s/%(uuid)s.vmdk' % {'uuid': self._uuid}
        if with_root_disk:
            mock_create_virtual_disk.assert_called_once_with(
                    self._session, self._dc_info.ref,
                    vi.ii.adapter_type, vi.ii.disk_type,
                    fake_path,
                    vi.root_gb * units.Mi)
            linked_clone = False
            mock_attach_disk_to_vm.assert_called_once_with(
                    "fake_vm_ref", self._instance,
                    vi.ii.adapter_type, vi.ii.disk_type,
                    fake_path,
                    vi.root_gb * units.Mi, linked_clone,
                    disk_io_limits=vi._extra_specs.disk_io_limits)

    def test_use_iso_image_with_root_disk(self):
        self._test_use_iso_image(with_root_disk=True)

    def test_use_iso_image_without_root_disk(self):
        self._test_use_iso_image(with_root_disk=False)

    def _verify_spawn_method_calls(self, mock_call_method, extras=None):
        # TODO(vui): More explicit assertions of spawn() behavior
        # are waiting on additional refactoring pertaining to image
        # handling/manipulation. Till then, we continue to assert on the
        # sequence of VIM operations invoked.
        expected_methods = ['get_object_property',
                            'SearchDatastore_Task',
                            'CreateVirtualDisk_Task',
                            'DeleteDatastoreFile_Task',
                            'MoveDatastoreFile_Task',
                            'DeleteDatastoreFile_Task',
                            'SearchDatastore_Task',
                            'ExtendVirtualDisk_Task',
        ]
        if extras:
            expected_methods.extend(extras)

        # Last call should be renaming the instance
        expected_methods.append('Rename_Task')
        recorded_methods = [c[1][1] for c in mock_call_method.mock_calls]
        self.assertEqual(expected_methods, recorded_methods)

    @mock.patch.object(vmops.VMwareVMOps, '_create_folders',
                       return_value='fake_vm_folder')
    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch(
        'nova.virt.vmwareapi.vmops.VMwareVMOps._update_vnic_index')
    @mock.patch(
        'nova.virt.vmwareapi.vmops.VMwareVMOps._configure_config_drive')
    @mock.patch('nova.virt.vmwareapi.ds_util.get_datastore')
    @mock.patch(
        'nova.virt.vmwareapi.vmops.VMwareVMOps.get_datacenter_ref_and_name')
    @mock.patch('nova.virt.vmwareapi.vif.get_vif_info',
                return_value=[])
    @mock.patch('nova.virt.vmwareapi.vm_util.get_vm_create_spec',
                return_value='fake_create_spec')
    @mock.patch('nova.virt.vmwareapi.vm_util.create_vm',
                return_value='fake_vm_ref')
    @mock.patch('nova.virt.vmwareapi.ds_util.mkdir')
    @mock.patch('nova.virt.vmwareapi.vmops.VMwareVMOps._set_machine_id')
    @mock.patch(
        'nova.virt.vmwareapi.imagecache.ImageCacheManager.enlist_image')
    @mock.patch.object(vmops.VMwareVMOps, '_get_and_set_vnc_config')
    @mock.patch('nova.virt.vmwareapi.vm_util.power_on_instance')
    @mock.patch('nova.virt.vmwareapi.vm_util.copy_virtual_disk')
    # TODO(dims): Need to add tests for create_virtual_disk after the
    #             disk/image code in spawn gets refactored
    def _test_spawn(self,
                   mock_copy_virtual_disk,
                   mock_power_on_instance,
                   mock_get_and_set_vnc_config,
                   mock_enlist_image,
                   mock_set_machine_id,
                   mock_mkdir,
                   mock_create_vm,
                   mock_get_create_spec,
                   mock_get_vif_info,
                   mock_get_datacenter_ref_and_name,
                   mock_get_datastore,
                   mock_configure_config_drive,
                   mock_update_vnic_index,
                   mock_update_cluster_placement,
                   mock_create_folders,
                   block_device_info=None,
                   extra_specs=None,
                   config_drive=False):

        if extra_specs is None:
            extra_specs = vm_util.ExtraSpecs()

        image_size = (self._instance.flavor.root_gb) * units.Gi / 2
        image = {
            'id': self._image_id,
            'disk_format': 'vmdk',
            'size': image_size,
            'owner': ''
        }
        image = objects.ImageMeta.from_dict(image)
        image_info = images.VMwareImage(
            image_id=self._image_id,
            file_size=image_size)
        vi = self._vmops._get_vm_config_info(
            self._instance, image_info, extra_specs)

        self._vmops._volumeops = mock.Mock()
        network_info = mock.Mock()
        mock_get_datastore.return_value = self._ds
        mock_get_datacenter_ref_and_name.return_value = self._dc_info
        mock_call_method = mock.Mock(return_value='fake_task')

        if extra_specs is None:
            extra_specs = vm_util.ExtraSpecs()

        with test.nested(
                mock.patch.object(self._session, '_wait_for_task'),
                mock.patch.object(self._session, '_call_method',
                                  mock_call_method),
                mock.patch.object(uuidutils, 'generate_uuid',
                                  return_value='tmp-uuid'),
                mock.patch.object(images, 'fetch_image'),
                mock.patch('nova.image.glance.API.get'),
                mock.patch.object(vutil, 'get_inventory_path',
                                  return_value=self._dc_info.name),
                mock.patch.object(self._vmops, '_get_extra_specs',
                                  return_value=extra_specs),
                mock.patch.object(self._vmops, '_get_instance_metadata',
                                  return_value='fake-metadata'),
                mock.patch.object(ds_util, 'file_size', return_value=0)
        ) as (_wait_for_task, _call_method, _generate_uuid, _fetch_image,
              _get_img_svc, _get_inventory_path, _get_extra_specs,
              _get_instance_metadata, file_size):
            self._vmops.spawn(self._context, self._instance, image,
                              injected_files='fake_files',
                              admin_password='password',
                              network_info=network_info,
                              block_device_info=block_device_info)

            self.assertEqual(2, mock_mkdir.call_count)

            mock_get_vif_info.assert_called_once_with(
                    self._session, self._cluster.obj,
                    constants.DEFAULT_VIF_MODEL, network_info)
            mock_get_create_spec.assert_called_once_with(
                    self._session.vim.client.factory,
                    self._instance,
                    'fake_ds',
                    [],
                    extra_specs,
                    constants.DEFAULT_OS_TYPE,
                    profile_spec=None,
                    metadata='fake-metadata')
            mock_create_vm.assert_called_once_with(
                    self._session,
                    self._instance,
                    'fake_vm_folder',
                    'fake_create_spec',
                    self._cluster.resourcePool)
            mock_get_and_set_vnc_config.assert_called_once_with(
                self._session.vim.client.factory,
                self._instance,
                'fake_vm_ref')
            mock_set_machine_id.assert_called_once_with(
                self._session.vim.client.factory,
                self._instance,
                network_info,
                vm_ref='fake_vm_ref')
            mock_power_on_instance.assert_called_once_with(
                self._session, self._instance, vm_ref='fake_vm_ref')

            if (block_device_info and
                'block_device_mapping' in block_device_info):
                bdms = block_device_info['block_device_mapping']
                for bdm in bdms:
                    mock_attach_root = (
                        self._vmops._volumeops.attach_root_volume)
                    mock_attach = self._vmops._volumeops.attach_volume
                    adapter_type = bdm.get('disk_bus') or vi.ii.adapter_type
                    if bdm.get('boot_index') == 0:
                        mock_attach_root.assert_any_call(
                            bdm['connection_info'], self._instance,
                            self._ds.ref, adapter_type)
                    else:
                        mock_attach.assert_any_call(
                            bdm['connection_info'], self._instance,
                            self._ds.ref, adapter_type)

            mock_enlist_image.assert_called_once_with(
                        self._image_id, self._ds, self._dc_info.ref)

            upload_file_name = 'vmware_temp/tmp-uuid/%s/%s-flat.vmdk' % (
                    self._image_id, self._image_id)
            _fetch_image.assert_called_once_with(
                    self._context,
                    self._instance,
                    self._session._host,
                    self._session._port,
                    self._dc_info.name,
                    self._ds.name,
                    upload_file_name,
                    cookies='Fake-CookieJar')
            self.assertGreater(len(_wait_for_task.mock_calls), 0)
            _get_inventory_path.call_count = 1
            extras = None
            if block_device_info and ('ephemerals' in block_device_info or
                                      'swap' in block_device_info):
                extras = ['CreateVirtualDisk_Task']
            self._verify_spawn_method_calls(_call_method, extras)

            dc_ref = 'fake_dc_ref'
            source_file = ('[fake_ds] vmware_base/%s/%s.vmdk' %
                          (self._image_id, self._image_id))
            dest_file = ('[fake_ds] vmware_base/%s/%s.%d.vmdk' %
                          (self._image_id, self._image_id,
                          self._instance['root_gb']))
            # TODO(dims): add more tests for copy_virtual_disk after
            # the disk/image code in spawn gets refactored
            mock_copy_virtual_disk.assert_called_with(self._session,
                                                      dc_ref,
                                                      source_file,
                                                      dest_file)

            if config_drive:
                mock_configure_config_drive.assert_called_once_with(
                        self._context, self._instance, 'fake_vm_ref',
                        self._dc_info, self._ds, 'fake_files', 'password',
                        network_info)
            mock_update_vnic_index.assert_called_once_with(
                        self._context, self._instance, network_info)

    @mock.patch.object(ds_util, 'get_datastore')
    @mock.patch.object(vmops.VMwareVMOps, 'get_datacenter_ref_and_name')
    def _test_get_spawn_vm_config_info(self,
                                       mock_get_datacenter_ref_and_name,
                                       mock_get_datastore,
                                       image_size_bytes=0):
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=image_size_bytes,
                linked_clone=True)

        mock_get_datastore.return_value = self._ds
        mock_get_datacenter_ref_and_name.return_value = self._dc_info
        extra_specs = vm_util.ExtraSpecs()

        vi = self._vmops._get_vm_config_info(self._instance, image_info,
                                             extra_specs)
        self.assertEqual(image_info, vi.ii)
        self.assertEqual(self._ds, vi.datastore)
        self.assertEqual(self._instance.flavor.root_gb, vi.root_gb)
        self.assertEqual(self._instance, vi.instance)
        self.assertEqual(self._instance.uuid, vi.instance.uuid)
        self.assertEqual(extra_specs, vi._extra_specs)

        cache_image_path = '[%s] vmware_base/%s/%s.vmdk' % (
            self._ds.name, self._image_id, self._image_id)
        self.assertEqual(cache_image_path, str(vi.cache_image_path))

        cache_image_folder = '[%s] vmware_base/%s' % (
            self._ds.name, self._image_id)
        self.assertEqual(cache_image_folder, str(vi.cache_image_folder))

    def test_get_spawn_vm_config_info(self):
        image_size = (self._instance.flavor.root_gb) * units.Gi / 2
        self._test_get_spawn_vm_config_info(image_size_bytes=image_size)

    def test_get_spawn_vm_config_info_image_too_big(self):
        image_size = (self._instance.flavor.root_gb + 1) * units.Gi
        self.assertRaises(exception.InstanceUnacceptable,
                          self._test_get_spawn_vm_config_info,
                          image_size_bytes=image_size)

    def test_spawn(self):
        self._test_spawn()

    def test_spawn_config_drive_enabled(self):
        self.flags(force_config_drive=True)
        self._test_spawn(config_drive=True)

    def test_spawn_with_block_device_info(self):
        block_device_info = {
            'block_device_mapping': [{'boot_index': 0,
                                      'connection_info': 'fake',
                                      'mount_device': '/dev/vda'}]
        }
        self._test_spawn(block_device_info=block_device_info)

    def test_spawn_with_block_device_info_with_config_drive(self):
        self.flags(force_config_drive=True)
        block_device_info = {
            'block_device_mapping': [{'boot_index': 0,
                                      'connection_info': 'fake',
                                      'mount_device': '/dev/vda'}]
        }
        self._test_spawn(block_device_info=block_device_info,
                         config_drive=True)

    def _spawn_with_block_device_info_ephemerals(self, ephemerals):
        block_device_info = {'ephemerals': ephemerals}
        self._test_spawn(block_device_info=block_device_info)

    def test_spawn_with_block_device_info_ephemerals(self):
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'virtio',
                       'device_name': '/dev/vdb',
                       'size': 1}]
        self._spawn_with_block_device_info_ephemerals(ephemerals)

    def test_spawn_with_block_device_info_ephemerals_no_disk_bus(self):
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': None,
                       'device_name': '/dev/vdb',
                       'size': 1}]
        self._spawn_with_block_device_info_ephemerals(ephemerals)

    def test_spawn_with_block_device_info_swap(self):
        block_device_info = {'swap': {'disk_bus': None,
                                      'swap_size': 512,
                                      'device_name': '/dev/sdb'}}
        self._test_spawn(block_device_info=block_device_info)

    @mock.patch.object(vm_util, 'rename_vm')
    @mock.patch('nova.virt.vmwareapi.vm_util.power_on_instance')
    @mock.patch.object(vmops.VMwareVMOps, '_create_and_attach_thin_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_use_disk_image_as_linked_clone')
    @mock.patch.object(vmops.VMwareVMOps, '_fetch_image_if_missing')
    @mock.patch(
        'nova.virt.vmwareapi.imagecache.ImageCacheManager.enlist_image')
    @mock.patch.object(vmops.VMwareVMOps, 'build_virtual_machine')
    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch.object(vmops.VMwareVMOps, '_get_vm_config_info')
    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(images.VMwareImage, 'from_image')
    def test_spawn_with_ephemerals_and_swap(self, from_image,
                                            get_extra_specs,
                                            get_vm_config_info,
                                            update_cluster_placement,
                                            build_virtual_machine,
                                            enlist_image,
                                            fetch_image,
                                            use_disk_image,
                                            create_and_attach_thin_disk,
                                            power_on_instance,
                                            rename_vm):
        self._instance.flavor = objects.Flavor(vcpus=1, memory_mb=512,
                                               name="m1.tiny", root_gb=1,
                                               ephemeral_gb=1, swap=512,
                                               extra_specs={})
        extra_specs = self._vmops._get_extra_specs(self._instance.flavor)
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': None,
                       'device_name': '/dev/vdb',
                       'size': 1},
                      {'device_type': 'disk',
                       'disk_bus': None,
                       'device_name': '/dev/vdc',
                       'size': 1}]
        swap = {'disk_bus': None, 'swap_size': 512, 'device_name': '/dev/vdd'}
        bdi = {'block_device_mapping': [], 'root_device_name': '/dev/sda',
               'ephemerals': ephemerals, 'swap': swap}
        metadata = self._vmops._get_instance_metadata(self._context,
                                                      self._instance)
        self.flags(enabled=False, group='vnc')
        self.flags(flat_injected=False)

        image_size = (self._instance.flavor.root_gb) * units.Gi / 2
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=image_size)
        vi = get_vm_config_info.return_value
        from_image.return_value = image_info
        build_virtual_machine.return_value = 'fake-vm-ref'

        self._vmops.spawn(self._context, self._instance, {},
                          injected_files=None, admin_password=None,
                          network_info=[], block_device_info=bdi)

        from_image.assert_called_once_with(
            self._context, self._instance.image_ref, {})
        get_vm_config_info.assert_called_once_with(self._instance,
            image_info, extra_specs)
        build_virtual_machine.assert_called_once_with(self._instance,
                                                      self._context,
            image_info, vi.dc_info, vi.datastore, [], extra_specs, metadata)
        enlist_image.assert_called_once_with(image_info.image_id,
                                             vi.datastore, vi.dc_info.ref)
        fetch_image.assert_called_once_with(self._context, vi)
        use_disk_image.assert_called_once_with('fake-vm-ref', vi)

        # _create_and_attach_thin_disk should be called for each ephemeral
        # and swap disk
        eph0_path = str(ds_obj.DatastorePath(vi.datastore.name,
                                             self._uuid,
                                             'ephemeral_0.vmdk'))
        eph1_path = str(ds_obj.DatastorePath(vi.datastore.name,
                                             self._uuid,
                                             'ephemeral_1.vmdk'))
        swap_path = str(ds_obj.DatastorePath(vi.datastore.name,
                                             self._uuid,
                                             'swap.vmdk'))
        create_and_attach_thin_disk.assert_has_calls([
            mock.call(self._instance, 'fake-vm-ref', vi.dc_info,
                      ephemerals[0]['size'] * units.Mi, vi.ii.adapter_type,
                      eph0_path),
            mock.call(self._instance, 'fake-vm-ref', vi.dc_info,
                      ephemerals[1]['size'] * units.Mi, vi.ii.adapter_type,
                      eph1_path),
            mock.call(self._instance, 'fake-vm-ref', vi.dc_info,
                      swap['swap_size'] * units.Ki, vi.ii.adapter_type,
                      swap_path)
        ])

        power_on_instance.assert_called_once_with(self._session,
                                                  self._instance,
                                                  vm_ref='fake-vm-ref')

    def _get_fake_vi(self):
        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=7,
                linked_clone=False)
        vi = vmops.VirtualMachineInstanceConfigInfo(
                self._instance, image_info,
                self._ds, self._dc_info, mock.Mock())
        return vi

    @mock.patch.object(vm_util, 'create_virtual_disk')
    def test_create_and_attach_thin_disk(self, mock_create):
        vi = self._get_fake_vi()
        self._vmops._volumeops = mock.Mock()
        mock_attach_disk_to_vm = self._vmops._volumeops.attach_disk_to_vm

        path = str(ds_obj.DatastorePath(vi.datastore.name, self._uuid,
                                        'fake-filename'))
        self._vmops._create_and_attach_thin_disk(self._instance,
                                                 'fake-vm-ref',
                                                 vi.dc_info, 1,
                                                 'fake-adapter-type',
                                                 path)
        mock_create.assert_called_once_with(
                self._session, self._dc_info.ref, 'fake-adapter-type',
                'thin', path, 1)
        mock_attach_disk_to_vm.assert_called_once_with(
                'fake-vm-ref', self._instance, 'fake-adapter-type',
                'thin', path, 1, False)

    def test_create_ephemeral_with_bdi(self):
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'virtio',
                       'device_name': '/dev/vdb',
                       'size': 1}]
        block_device_info = {'ephemerals': ephemerals}
        vi = self._get_fake_vi()
        with mock.patch.object(
            self._vmops, '_create_and_attach_thin_disk') as mock_caa:
            self._vmops._create_ephemeral(block_device_info,
                                          self._instance,
                                          'fake-vm-ref',
                                          vi.dc_info, vi.datastore,
                                          self._uuid,
                                          vi.ii.adapter_type)
            mock_caa.assert_called_once_with(
                self._instance, 'fake-vm-ref',
                vi.dc_info, 1 * units.Mi, 'virtio',
                '[fake_ds] %s/ephemeral_0.vmdk' % self._uuid)

    def _test_create_ephemeral_from_instance(self, bdi):
        vi = self._get_fake_vi()
        with mock.patch.object(
            self._vmops, '_create_and_attach_thin_disk') as mock_caa:
            self._vmops._create_ephemeral(bdi,
                                          self._instance,
                                          'fake-vm-ref',
                                          vi.dc_info, vi.datastore,
                                          self._uuid,
                                          vi.ii.adapter_type)
            mock_caa.assert_called_once_with(
                self._instance, 'fake-vm-ref',
                vi.dc_info, 1 * units.Mi, constants.DEFAULT_ADAPTER_TYPE,
                '[fake_ds] %s/ephemeral_0.vmdk' % self._uuid)

    def test_create_ephemeral_with_bdi_but_no_ephemerals(self):
        block_device_info = {'ephemerals': []}
        self._instance.flavor.ephemeral_gb = 1
        self._test_create_ephemeral_from_instance(block_device_info)

    def test_create_ephemeral_with_no_bdi(self):
        self._instance.flavor.ephemeral_gb = 1
        self._test_create_ephemeral_from_instance(None)

    def _test_create_swap_from_instance(self, bdi):
        vi = self._get_fake_vi()
        flavor = objects.Flavor(vcpus=1, memory_mb=1024, ephemeral_gb=1,
                                swap=1024, extra_specs={})
        self._instance.flavor = flavor
        with mock.patch.object(
            self._vmops, '_create_and_attach_thin_disk'
        ) as create_and_attach:
            self._vmops._create_swap(bdi, self._instance, 'fake-vm-ref',
                                     vi.dc_info, vi.datastore, self._uuid,
                                     'lsiLogic')
            size = flavor.swap * units.Ki
            if bdi is not None:
                swap = bdi.get('swap', {})
                size = swap.get('swap_size', 0) * units.Ki
            path = str(ds_obj.DatastorePath(vi.datastore.name, self._uuid,
                                             'swap.vmdk'))
            create_and_attach.assert_called_once_with(self._instance,
                'fake-vm-ref', vi.dc_info, size, 'lsiLogic', path)

    def test_create_swap_with_bdi(self):
        block_device_info = {'swap': {'disk_bus': None,
                                      'swap_size': 512,
                                      'device_name': '/dev/sdb'}}
        self._test_create_swap_from_instance(block_device_info)

    def test_create_swap_with_no_bdi(self):
        self._test_create_swap_from_instance(None)

    @mock.patch.object(vm_util, 'update_cluster_placement')
    @mock.patch.object(vmops.VMwareVMOps, '_create_folders',
                       return_value='fake_vm_folder')
    def test_build_virtual_machine(self, mock_create_folder,
                                   mock_update_cluster_placement):
        image = images.VMwareImage(image_id=self._image_id)

        extra_specs = vm_util.ExtraSpecs()

        vm_ref = self._vmops.build_virtual_machine(self._instance,
                                                   self._context,
                                                   image, self._dc_info,
                                                   self._ds,
                                                   self.network_info,
                                                   extra_specs,
                                                   self._metadata)

        vm = vmwareapi_fake._get_object(vm_ref)

        # Test basic VM parameters
        self.assertEqual(self._instance.uuid, vm.name)
        self.assertEqual(self._instance.uuid,
                         vm.get('summary.config.instanceUuid'))
        self.assertEqual(self._instance_values['vcpus'],
                         vm.get('summary.config.numCpu'))
        self.assertEqual(self._instance_values['memory_mb'],
                         vm.get('summary.config.memorySizeMB'))

        # Test NSX config
        for optval in vm.get('config.extraConfig').OptionValue:
            if optval.key == 'nvp.vm-uuid':
                self.assertEqual(self._instance_values['uuid'], optval.value)
                break
        else:
            self.fail('nvp.vm-uuid not found in extraConfig')

        # Test that the VM is associated with the specified datastore
        datastores = vm.datastore.ManagedObjectReference
        self.assertEqual(1, len(datastores))

        datastore = vmwareapi_fake._get_object(datastores[0])
        self.assertEqual(self._ds.name, datastore.get('summary.name'))

        # Test that the VM's network is configured as specified
        devices = vm.get('config.hardware.device').VirtualDevice
        for device in devices:
            if device.obj_name != 'ns0:VirtualE1000':
                continue
            self.assertEqual(self._network_values['address'],
                             device.macAddress)
            break
        else:
            self.fail('NIC not configured')

    def test_spawn_cpu_limit(self):
        cpu_limits = vm_util.Limits(limit=7)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_cpu_reservation(self):
        cpu_limits = vm_util.Limits(reservation=7)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_cpu_allocations(self):
        cpu_limits = vm_util.Limits(limit=7,
                                    reservation=6)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_cpu_shares_level(self):
        cpu_limits = vm_util.Limits(shares_level='high')
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_cpu_shares_custom(self):
        cpu_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=1948)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_memory_limit(self):
        memory_limits = vm_util.Limits(limit=7)
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_memory_reservation(self):
        memory_limits = vm_util.Limits(reservation=7)
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_memory_allocations(self):
        memory_limits = vm_util.Limits(limit=7,
                                       reservation=6)
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_memory_shares_level(self):
        memory_limits = vm_util.Limits(shares_level='high')
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_memory_shares_custom(self):
        memory_limits = vm_util.Limits(shares_level='custom',
                                       shares_share=1948)
        extra_specs = vm_util.ExtraSpecs(memory_limits=memory_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_vif_limit(self):
        vif_limits = vm_util.Limits(limit=7)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_vif_reservation(self):
        vif_limits = vm_util.Limits(reservation=7)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_vif_shares_level(self):
        vif_limits = vm_util.Limits(shares_level='high')
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self._test_spawn(extra_specs=extra_specs)

    def test_spawn_vif_shares_custom(self):
        vif_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=1948)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self._test_spawn(extra_specs=extra_specs)

    def _validate_extra_specs(self, expected, actual):
        self.assertEqual(expected.cpu_limits.limit,
                         actual.cpu_limits.limit)
        self.assertEqual(expected.cpu_limits.reservation,
                         actual.cpu_limits.reservation)
        self.assertEqual(expected.cpu_limits.shares_level,
                         actual.cpu_limits.shares_level)
        self.assertEqual(expected.cpu_limits.shares_share,
                         actual.cpu_limits.shares_share)

    def _validate_flavor_extra_specs(self, flavor_extra_specs, expected):
        # Validate that the extra specs are parsed correctly
        flavor = objects.Flavor(name='my-flavor',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs=flavor_extra_specs)
        flavor_extra_specs = self._vmops._get_extra_specs(flavor, None)
        self._validate_extra_specs(expected, flavor_extra_specs)

    """
    The test covers the negative failure scenario, where `hw_video_ram`,
    coming from the image is bigger than the maximum allowed video ram from
    the flavor.
    """
    def test_video_ram(self):
        meta_dict = {'id': self._image_id, 'properties': {'hw_video_ram': 120}}
        image_meta, flavor = self._get_image_and_flavor_for_test_video(
            meta_dict)

        self.assertRaises(exception.RequestedVRamTooHigh,
                          self._vmops._get_extra_specs,
                          flavor,
                          image_meta)

    """
    Testing VM provisioning result in the case where `hw_video_ram`,
    coming from the image is not specified. This is a success scenario,
    in the case where `hw_video_ram` property is not set.
    """
    def test_video_ram_if_none(self):
        meta_dict = {'id': self._image_id, 'properties': {}}
        image_meta, flavor = self._get_image_and_flavor_for_test_video(
            meta_dict)

        extra_specs = self._vmops._get_extra_specs(flavor, image_meta)
        self.assertIsNone(extra_specs.hw_video_ram)

    """
    Testing VM provisioning result in the case where `hw_video:ram_max_mb`,
    coming from the flavor is not specified. This is a success scenario,
    in the case where `hw_video_ram` property is not set.
    """
    def test_max_video_ram_none(self):
        meta_dict = {'id': self._image_id, 'properties': {'hw_video_ram': 120}}
        image_meta = objects.ImageMeta.from_dict(meta_dict)
        flavor_extra_specs = {'quota:cpu_limit': 7,
                              'quota:cpu_reservation': 6}
        flavor = objects.Flavor(name='my-flavor',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs=flavor_extra_specs)

        self.assertRaises(exception.RequestedVRamTooHigh,
                          self._vmops._get_extra_specs,
                          flavor,
                          image_meta)

    """
    Testing VM provisioning result in the case where `hw_video_ram`,
    coming from the image is less than the maximum allowed video ram from
    the flavor. This is a success scenario, in the case where `hw_video_ram`
    property is set in the extra spec.
    """
    def test_success_video_ram(self):
        expected_video_ram = 90
        meta_dict = {'id': self._image_id, 'properties': {
            'hw_video_ram': expected_video_ram}}
        image_meta, flavor = self._get_image_and_flavor_for_test_video(
            meta_dict)

        extra_specs = self._vmops._get_extra_specs(flavor, image_meta)
        self.assertEqual(self._calculate_expected_fake_video_ram(
            expected_video_ram), extra_specs.hw_video_ram)

    """
    Testing VM provisioning result in the case where `hw_video_ram`,
    coming from the image is equal to 0. This is a success scenario, in the
    case where `hw_video_ram` property is not set in the extra spec.
    """
    def test_zero_video_ram(self):
        meta_dict = {'id': self._image_id, 'properties': {'hw_video_ram': 0}}
        image_meta, flavor = self._get_image_and_flavor_for_test_video(
            meta_dict)

        extra_specs = self._vmops._get_extra_specs(flavor, image_meta)
        self.assertIsNone(extra_specs.hw_video_ram)

    def _calculate_expected_fake_video_ram(self, amount):
        return amount * units.Mi / units.Ki

    def _get_image_and_flavor_for_test_video(self, meta_dict):
        image_meta = objects.ImageMeta.from_dict(meta_dict)
        flavor_extra_specs = {'quota:cpu_limit': 7,
                              'quota:cpu_reservation': 6,
                              'hw_video:ram_max_mb': 100}
        flavor = objects.Flavor(name='my-flavor',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs=flavor_extra_specs)
        return image_meta, flavor

    def test_extra_specs_cpu_limit(self):
        flavor_extra_specs = {'quota:cpu_limit': 7}
        cpu_limits = vm_util.Limits(limit=7)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_cpu_reservations(self):
        flavor_extra_specs = {'quota:cpu_reservation': 7}
        cpu_limits = vm_util.Limits(reservation=7)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_cpu_allocations(self):
        flavor_extra_specs = {'quota:cpu_limit': 7,
                              'quota:cpu_reservation': 6}
        cpu_limits = vm_util.Limits(limit=7,
                                    reservation=6)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_cpu_shares_level(self):
        flavor_extra_specs = {'quota:cpu_shares_level': 'high'}
        cpu_limits = vm_util.Limits(shares_level='high')
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_cpu_shares_custom(self):
        flavor_extra_specs = {'quota:cpu_shares_level': 'custom',
                              'quota:cpu_shares_share': 1948}
        cpu_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=1948)
        extra_specs = vm_util.ExtraSpecs(cpu_limits=cpu_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_vif_shares_custom_pos01(self):
        flavor_extra_specs = {'quota:vif_shares_level': 'custom',
                              'quota:vif_shares_share': 40}
        vif_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=40)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self._validate_flavor_extra_specs(flavor_extra_specs, extra_specs)

    def test_extra_specs_vif_shares_with_invalid_level(self):
        flavor_extra_specs = {'quota:vif_shares_level': 'high',
                              'quota:vif_shares_share': 40}
        vif_limits = vm_util.Limits(shares_level='custom',
                                       shares_share=40)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        self.assertRaises(exception.InvalidInput,
            self._validate_flavor_extra_specs, flavor_extra_specs, extra_specs)

    def _make_vm_config_info(self, is_iso=False, is_sparse_disk=False,
                             vsphere_location=None):
        disk_type = (constants.DISK_TYPE_SPARSE if is_sparse_disk
                     else constants.DEFAULT_DISK_TYPE)
        file_type = (constants.DISK_FORMAT_ISO if is_iso
                     else constants.DEFAULT_DISK_FORMAT)

        image_info = images.VMwareImage(
                image_id=self._image_id,
                file_size=10 * units.Mi,
                file_type=file_type,
                disk_type=disk_type,
                linked_clone=True,
                vsphere_location=vsphere_location)
        cache_root_folder = self._ds.build_path("vmware_base", self._image_id)
        mock_imagecache = mock.Mock()
        mock_imagecache.get_image_cache_folder.return_value = cache_root_folder
        vi = vmops.VirtualMachineInstanceConfigInfo(
                self._instance, image_info,
                self._ds, self._dc_info, mock_imagecache)
        return vi

    @mock.patch.object(vmops.VMwareVMOps, 'check_cache_folder')
    @mock.patch.object(vmops.VMwareVMOps, '_fetch_image_as_file')
    @mock.patch.object(vmops.VMwareVMOps, '_prepare_iso_image')
    @mock.patch.object(vmops.VMwareVMOps, '_prepare_sparse_image')
    @mock.patch.object(vmops.VMwareVMOps, '_prepare_flat_image')
    @mock.patch.object(vmops.VMwareVMOps, '_cache_iso_image')
    @mock.patch.object(vmops.VMwareVMOps, '_cache_sparse_image')
    @mock.patch.object(vmops.VMwareVMOps, '_cache_flat_image')
    @mock.patch.object(vmops.VMwareVMOps, '_delete_datastore_file')
    @mock.patch.object(vmops.VMwareVMOps, '_update_image_size')
    def _test_fetch_image_if_missing(self,
                                     mock_update_image_size,
                                     mock_delete_datastore_file,
                                     mock_cache_flat_image,
                                     mock_cache_sparse_image,
                                     mock_cache_iso_image,
                                     mock_prepare_flat_image,
                                     mock_prepare_sparse_image,
                                     mock_prepare_iso_image,
                                     mock_fetch_image_as_file,
                                     mock_check_cache_folder,
                                     is_iso=False,
                                     is_sparse_disk=False):

        tmp_dir_path = mock.Mock()
        tmp_image_path = mock.Mock()
        if is_iso:
            mock_prepare = mock_prepare_iso_image
            mock_cache = mock_cache_iso_image
        elif is_sparse_disk:
            mock_prepare = mock_prepare_sparse_image
            mock_cache = mock_cache_sparse_image
        else:
            mock_prepare = mock_prepare_flat_image
            mock_cache = mock_cache_flat_image
        mock_prepare.return_value = tmp_dir_path, tmp_image_path

        vi = self._make_vm_config_info(is_iso, is_sparse_disk)
        self._vmops._fetch_image_if_missing(self._context, vi)

        mock_check_cache_folder.assert_called_once_with(
                self._ds.name, self._ds.ref)
        mock_prepare.assert_called_once_with(vi)
        mock_fetch_image_as_file.assert_called_once_with(
                self._context, vi, tmp_image_path)
        mock_cache.assert_called_once_with(vi, tmp_image_path)
        mock_delete_datastore_file.assert_called_once_with(
                str(tmp_dir_path), self._dc_info.ref)
        if is_sparse_disk:
            mock_update_image_size.assert_called_once_with(vi)

    def test_fetch_image_if_missing(self):
        self._test_fetch_image_if_missing()

    def test_fetch_image_if_missing_with_sparse(self):
        self._test_fetch_image_if_missing(
                is_sparse_disk=True)

    def test_fetch_image_if_missing_with_iso(self):
        self._test_fetch_image_if_missing(
                is_iso=True)

    def test_get_esx_host_and_cookies(self):
        datastore = mock.Mock()
        datastore.get_connected_hosts.return_value = ['fira-host']
        file_path = mock.Mock()

        def fake_invoke(module, method, *args, **kwargs):
            if method == 'AcquireGenericServiceTicket':
                ticket = mock.Mock()
                ticket.id = 'fira-ticket'
                return ticket
            elif method == 'get_object_property':
                return 'fira-host'
        with mock.patch.object(self._session, 'invoke_api', fake_invoke):
            result = self._vmops._get_esx_host_and_cookies(datastore,
                                                           'ha-datacenter',
                                                           file_path)
            self.assertEqual('fira-host', result[0])
            cookies = result[1]
            self.assertEqual(1, len(cookies))
            self.assertEqual('vmware_cgi_ticket', cookies[0].name)
            self.assertEqual('"fira-ticket"', cookies[0].value)

    def test_fetch_vsphere_image(self):
        vsphere_location = 'vsphere://my?dcPath=mycenter&dsName=mystore'
        vi = self._make_vm_config_info(vsphere_location=vsphere_location)
        image_ds_loc = mock.Mock()
        datacenter_moref = mock.Mock()
        fake_copy_task = mock.Mock()

        with test.nested(
                mock.patch.object(
                    self._session, 'invoke_api',
                    side_effect=[datacenter_moref, fake_copy_task]),
                mock.patch.object(self._session, '_wait_for_task')) as (
                    invoke_api, wait_for_task):
            self._vmops._fetch_vsphere_image(self._context, vi, image_ds_loc)
            expected_calls = [
                mock.call(
                    self._session.vim, 'FindByInventoryPath',
                    self._session.vim.service_content.searchIndex,
                    inventoryPath='mycenter'),
                mock.call(self._session.vim, 'CopyDatastoreFile_Task',
                    self._session.vim.service_content.fileManager,
                    destinationDatacenter=self._dc_info.ref,
                    destinationName=str(image_ds_loc),
                    sourceDatacenter=datacenter_moref,
                    sourceName='[mystore]')]
            invoke_api.assert_has_calls(expected_calls)
            wait_for_task.assert_called_once_with(fake_copy_task)

    @mock.patch.object(images, 'fetch_image')
    @mock.patch.object(vmops.VMwareVMOps, '_get_esx_host_and_cookies')
    def test_fetch_image_as_file(self,
                        mock_get_esx_host_and_cookies,
                        mock_fetch_image):
        vi = self._make_vm_config_info()
        image_ds_loc = mock.Mock()
        host = mock.Mock()
        dc_name = 'ha-datacenter'
        cookies = mock.Mock()
        mock_get_esx_host_and_cookies.return_value = host, cookies
        self._vmops._fetch_image_as_file(self._context, vi, image_ds_loc)
        mock_get_esx_host_and_cookies.assert_called_once_with(
                vi.datastore,
                dc_name,
                image_ds_loc.rel_path)
        mock_fetch_image.assert_called_once_with(
                self._context,
                vi.instance,
                host,
                self._session._port,
                dc_name,
                self._ds.name,
                image_ds_loc.rel_path,
                cookies=cookies)

    @mock.patch.object(vutil, 'get_inventory_path')
    @mock.patch.object(images, 'fetch_image')
    @mock.patch.object(vmops.VMwareVMOps, '_get_esx_host_and_cookies')
    def test_fetch_image_as_file_exception(self,
                                 mock_get_esx_host_and_cookies,
                                 mock_fetch_image,
                                 mock_get_inventory_path):
        vi = self._make_vm_config_info()
        image_ds_loc = mock.Mock()
        dc_name = 'ha-datacenter'
        mock_get_esx_host_and_cookies.side_effect = \
            exception.HostNotFound(host='')
        mock_get_inventory_path.return_value = self._dc_info.name
        self._vmops._fetch_image_as_file(self._context, vi, image_ds_loc)
        mock_get_esx_host_and_cookies.assert_called_once_with(
                vi.datastore,
                dc_name,
                image_ds_loc.rel_path)
        mock_fetch_image.assert_called_once_with(
                self._context,
                vi.instance,
                self._session._host,
                self._session._port,
                self._dc_info.name,
                self._ds.name,
                image_ds_loc.rel_path,
                cookies='Fake-CookieJar')

    @mock.patch.object(images, 'fetch_image_stream_optimized',
                       return_value=(123, '123'))
    @mock.patch.object(vmops.VMwareVMOps, '_get_project_folder')
    @mock.patch.object(vmops.VMwareVMOps, '_get_image_template_vm_name',
                       return_value='fake-name')
    def test_fetch_image_as_vapp(self, mock_template_vm_name,
                                 mock_get_project_folder,
                                 mock_fetch_image):
        vi = self._make_vm_config_info()
        mock_get_project_folder.return_value = vi.dc_info.vmFolder
        image_ds_loc = mock.Mock()
        image_ds_loc.parent.basename = 'fake-name'
        self._vmops._fetch_image_as_vapp(self._context, vi, image_ds_loc)
        mock_fetch_image.assert_called_once_with(
                self._context,
                vi.instance,
                self._session,
                'fake-name',
                self._ds.name,
                vi.dc_info.vmFolder,
                self._vmops._root_resource_pool)
        self.assertEqual(vi.ii.file_size, 123)

    @mock.patch.object(images, 'fetch_image_ova', return_value=(123, '123'))
    @mock.patch.object(vmops.VMwareVMOps, '_get_project_folder')
    @mock.patch.object(vmops.VMwareVMOps, '_get_image_template_vm_name',
                       return_value='fake-name')
    def test_fetch_image_as_ova(self, mock_template_vm_name,
                                mock_get_project_folder,
                                mock_fetch_image):
        vi = self._make_vm_config_info()
        mock_get_project_folder.return_value = vi.dc_info.vmFolder
        image_ds_loc = mock.Mock()
        image_ds_loc.parent.basename = 'fake-name'
        self._vmops._fetch_image_as_ova(self._context, vi, image_ds_loc)

        mock_template_vm_name.assert_called_once_with(
            vi.ii.image_id, vi.datastore.name
        )

        mock_fetch_image.assert_called_once_with(
                self._context,
                vi.instance,
                self._session,
                'fake-name',
                self._ds.name,
                vi.dc_info.vmFolder,
                self._vmops._root_resource_pool)
        self.assertEqual(vi.ii.file_size, 123)

    @mock.patch.object(uuidutils, 'generate_uuid', return_value='tmp-uuid')
    def test_prepare_iso_image(self, mock_generate_uuid):
        vi = self._make_vm_config_info(is_iso=True)
        tmp_dir_loc, tmp_image_ds_loc = self._vmops._prepare_iso_image(vi)

        expected_tmp_dir_path = '[%s] vmware_temp/tmp-uuid' % (self._ds.name)
        expected_image_path = '[%s] vmware_temp/tmp-uuid/%s/%s.iso' % (
                self._ds.name, self._image_id, self._image_id)

        self.assertEqual(str(tmp_dir_loc), expected_tmp_dir_path)
        self.assertEqual(str(tmp_image_ds_loc), expected_image_path)

    @mock.patch.object(uuidutils, 'generate_uuid', return_value='tmp-uuid')
    @mock.patch.object(ds_util, 'mkdir')
    def test_prepare_sparse_image(self, mock_mkdir, mock_generate_uuid):
        vi = self._make_vm_config_info(is_sparse_disk=True)
        tmp_dir_loc, tmp_image_ds_loc = self._vmops._prepare_sparse_image(vi)

        expected_tmp_dir_path = '[%s] vmware_temp/tmp-uuid' % (self._ds.name)
        expected_image_path = '[%s] vmware_temp/tmp-uuid/%s/%s' % (
                self._ds.name, self._image_id, "tmp-sparse.vmdk")

        self.assertEqual(str(tmp_dir_loc), expected_tmp_dir_path)
        self.assertEqual(str(tmp_image_ds_loc), expected_image_path)
        mock_mkdir.assert_called_once_with(self._session,
                                           tmp_image_ds_loc.parent,
                                           vi.dc_info.ref)

    @mock.patch.object(ds_util, 'mkdir')
    @mock.patch.object(vm_util, 'create_virtual_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_delete_datastore_file')
    @mock.patch.object(uuidutils, 'generate_uuid', return_value='tmp-uuid')
    def test_prepare_flat_image(self,
                                mock_generate_uuid,
                                mock_delete_datastore_file,
                                mock_create_virtual_disk,
                                mock_mkdir):
        vi = self._make_vm_config_info()
        tmp_dir_loc, tmp_image_ds_loc = self._vmops._prepare_flat_image(vi)

        expected_tmp_dir_path = '[%s] vmware_temp/tmp-uuid' % (self._ds.name)
        expected_image_path = '[%s] vmware_temp/tmp-uuid/%s/%s-flat.vmdk' % (
                self._ds.name, self._image_id, self._image_id)
        expected_image_path_parent = '[%s] vmware_temp/tmp-uuid/%s' % (
                self._ds.name, self._image_id)
        expected_path_to_create = '[%s] vmware_temp/tmp-uuid/%s/%s.vmdk' % (
                self._ds.name, self._image_id, self._image_id)

        mock_mkdir.assert_called_once_with(
                self._session, DsPathMatcher(expected_image_path_parent),
                self._dc_info.ref)

        self.assertEqual(str(tmp_dir_loc), expected_tmp_dir_path)
        self.assertEqual(str(tmp_image_ds_loc), expected_image_path)

        image_info = vi.ii
        mock_create_virtual_disk.assert_called_once_with(
            self._session, self._dc_info.ref,
            image_info.adapter_type,
            image_info.disk_type,
            DsPathMatcher(expected_path_to_create),
            image_info.file_size_in_kb)
        mock_delete_datastore_file.assert_called_once_with(
                DsPathMatcher(expected_image_path),
                self._dc_info.ref)

    @mock.patch.object(ds_util, 'file_move')
    def test_cache_iso_image(self, mock_file_move):
        vi = self._make_vm_config_info(is_iso=True)
        tmp_image_ds_loc = mock.Mock()

        self._vmops._cache_iso_image(vi, tmp_image_ds_loc)

        mock_file_move.assert_called_once_with(
                self._session, self._dc_info.ref,
                tmp_image_ds_loc.parent,
                DsPathMatcher('[fake_ds] vmware_base/%s' % self._image_id))

    @mock.patch.object(ds_util, 'file_move')
    def test_cache_flat_image(self, mock_file_move):
        vi = self._make_vm_config_info()
        tmp_image_ds_loc = mock.Mock()

        self._vmops._cache_flat_image(vi, tmp_image_ds_loc)

        mock_file_move.assert_called_once_with(
                self._session, self._dc_info.ref,
                tmp_image_ds_loc.parent,
                DsPathMatcher('[fake_ds] vmware_base/%s' % self._image_id))

    @mock.patch.object(ds_util, 'disk_move')
    @mock.patch.object(ds_util, 'mkdir')
    def test_cache_stream_optimized_image(self, mock_mkdir, mock_disk_move):
        vi = self._make_vm_config_info()

        self._vmops._cache_stream_optimized_image(vi, mock.sentinel.tmp_image)

        mock_mkdir.assert_called_once_with(
            self._session,
            DsPathMatcher('[fake_ds] vmware_base/%s' % self._image_id),
            self._dc_info.ref)
        mock_disk_move.assert_called_once_with(
                self._session, self._dc_info.ref,
                mock.sentinel.tmp_image,
                DsPathMatcher('[fake_ds] vmware_base/%s/%s.vmdk' %
                              (self._image_id, self._image_id)))

    @mock.patch.object(ds_util, 'file_move')
    @mock.patch.object(vm_util, 'copy_virtual_disk')
    @mock.patch.object(vmops.VMwareVMOps, '_delete_datastore_file')
    def test_cache_sparse_image(self,
                                mock_delete_datastore_file,
                                mock_copy_virtual_disk,
                                mock_file_move):
        vi = self._make_vm_config_info(is_sparse_disk=True)

        sparse_disk_path = "[%s] vmware_temp/tmp-uuid/%s/tmp-sparse.vmdk" % (
                self._ds.name, self._image_id)
        tmp_image_ds_loc = ds_obj.DatastorePath.parse(sparse_disk_path)

        self._vmops._cache_sparse_image(vi, tmp_image_ds_loc)

        target_disk_path = "[%s] vmware_temp/tmp-uuid/%s/%s.vmdk" % (
                self._ds.name,
                self._image_id, self._image_id)
        mock_copy_virtual_disk.assert_called_once_with(
                self._session, self._dc_info.ref,
                sparse_disk_path,
                DsPathMatcher(target_disk_path))

    def test_get_storage_policy_none(self):
        flavor = objects.Flavor(name='m1.small',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs={})
        self.flags(pbm_enabled=True,
                   pbm_default_policy='fake-policy', group='vmware')
        extra_specs = self._vmops._get_extra_specs(flavor, None)
        self.assertEqual('fake-policy', extra_specs.storage_policy)

    def test_get_storage_policy_extra_specs(self):
        extra_specs = {'vmware:storage_policy': 'flavor-policy'}
        flavor = objects.Flavor(name='m1.small',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs=extra_specs)
        self.flags(pbm_enabled=True,
                   pbm_default_policy='default-policy', group='vmware')
        extra_specs = self._vmops._get_extra_specs(flavor, None)
        self.assertEqual('flavor-policy', extra_specs.storage_policy)

    def test_get_base_folder_not_set(self):
        self.flags(subdirectory_name='vmware_base', group='image_cache')
        base_folder = self._vmops._get_base_folder()
        self.assertEqual('vmware_base', base_folder)

    def test_get_base_folder_host_ip(self):
        self.flags(my_ip='7.7.7.7')
        self.flags(subdirectory_name='_base', group='image_cache')
        base_folder = self._vmops._get_base_folder()
        self.assertEqual('7.7.7.7_base', base_folder)

    def test_get_base_folder_cache_prefix(self):
        self.flags(cache_prefix='my_prefix', group='vmware')
        self.flags(subdirectory_name='_base', group='image_cache')
        base_folder = self._vmops._get_base_folder()
        self.assertEqual('my_prefix_base', base_folder)

    @mock.patch.object(vmops.VMwareVMOps, '_get_instance_props')
    def _test_reboot_vm(self, get_instance_props,
                        reboot_type="SOFT", tool_status=True):

        expected_methods = ['get_object_properties_dict']
        get_instance_props.return_value = {
                    "runtime.powerState": "poweredOn",
                    "summary.guest.toolsStatus": "toolsOk",
                    "summary.guest.toolsRunningStatus": "guestToolsRunning"}
        if reboot_type == "SOFT":
            expected_methods.append('RebootGuest')
        else:
            expected_methods.append('ResetVM_Task')

        def fake_call_method(module, method, *args, **kwargs):
            if method == 'get_object_properties_dict' and tool_status:
                return {
                    "runtime.powerState": "poweredOn",
                    "summary.guest.toolsStatus": "toolsOk",
                    "summary.guest.toolsRunningStatus": "guestToolsRunning"}
            elif method == 'get_object_properties_dict':
                return {"runtime.powerState": "poweredOn"}
            elif method == 'CreatePropertyCollector':
                return {
                    "runtime.powerState": "poweredOn",
                    "summary.guest.toolsStatus": "toolsOk",
                    "summary.guest.toolsRunningStatus": "guestToolsRunning"}
            elif method == 'ResetVM_Task':
                return 'fake-task'

        with test.nested(
            mock.patch.object(vm_util, "get_vm_ref",
                              return_value='fake-vm-ref'),
            mock.patch.object(self._session, "_call_method",
                              fake_call_method),
            mock.patch.object(self._session, "_wait_for_task")
        ) as (_get_vm_ref, fake_call_method, _wait_for_task):
            self._vmops.reboot(self._instance, self.network_info, reboot_type)
            _get_vm_ref.assert_called_once_with(self._session,
                                                self._instance)
            if reboot_type == "HARD":
                _wait_for_task.assert_has_calls([
                       mock.call('fake-task')])

    def test_reboot_vm_soft(self):
        self._test_reboot_vm()

    def test_reboot_vm_hard_toolstatus(self):
        self._test_reboot_vm(reboot_type="HARD", tool_status=False)

    def test_reboot_vm_hard(self):
        self._test_reboot_vm(reboot_type="HARD")

    def test_get_instance_metadata(self):
        flavor = objects.Flavor(id=7,
                                name='m1.small',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs={})
        self._instance.flavor = flavor
        metadata = self._vmops._get_instance_metadata(
            self._context, self._instance)
        expected = ("name:fake_display_name\n"
                    "userid:fake_user\n"
                    "username:None\n"
                    "projectid:fake_project\n"
                    "projectname:None\n"
                    "flavor:name:m1.small\n"
                    "flavor:memory_mb:6\n"
                    "flavor:vcpus:28\n"
                    "flavor:ephemeral_gb:8128\n"
                    "flavor:root_gb:496\n"
                    "flavor:swap:33550336\n"
                    "imageid:%s\n"
                    "package:%s\n" % (
                        uuids.image,
                        version.version_string_with_package()))
        self.assertEqual(expected, metadata)

    def test_get_instance_metadata_flavor(self):
        # Construct a flavor different from instance.flavor
        flavor_int_meta_fields = ['memory_mb',
                                  'vcpus',
                                  'root_gb',
                                  'ephemeral_gb',
                                  'swap']
        flavor = self._instance.flavor.obj_clone()
        for field in flavor_int_meta_fields:
            # Set int fields of flavor to instance.flavor value + 1
            setattr(flavor, field, getattr(self._instance.flavor, field) + 1)
        flavor.name = self._instance.flavor.name + '1'

        metadata = self._vmops._get_instance_metadata(
            self._context, self._instance, flavor)

        # Verify metadata contains the values from flavor parameter
        meta_lines = metadata.split('\n')
        flavor_meta_fields = flavor_int_meta_fields[:]
        flavor_meta_fields.append('name')
        for field in flavor_meta_fields:
            meta_repr = 'flavor:%s:%s' % (field, getattr(flavor, field))
            self.assertIn(meta_repr, meta_lines)

    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'get_network_attach_config_spec',
                       return_value='fake-attach-spec')
    @mock.patch.object(vm_util, 'get_attach_port_index', return_value=1)
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def test_attach_interface(self, mock_get_vm_ref,
                              mock_get_attach_port_index,
                              mock_get_network_attach_config_spec,
                              mock_reconfigure_vm,
                              mock_extra_specs):
        _network_api = mock.Mock()
        self._vmops._network_api = _network_api

        vif_info = vif.get_vif_dict(self._session, self._cluster,
                                    'VirtualE1000', self._network_values)
        extra_specs = vm_util.ExtraSpecs()
        mock_extra_specs.return_value = extra_specs
        self._vmops.attach_interface(self._context, self._instance,
                                     self._image_meta, self._network_values)
        mock_get_vm_ref.assert_called_once_with(self._session, self._instance)
        mock_get_attach_port_index.assert_called_once_with(self._session,
                                                           'fake-ref')
        mock_get_network_attach_config_spec.assert_called_once_with(
            self._session.vim.client.factory, vif_info, 1,
            extra_specs.vif_limits)
        mock_reconfigure_vm.assert_called_once_with(self._session,
                                                    'fake-ref',
                                                    'fake-attach-spec')
        _network_api.update_instance_vnic_index.assert_called_once_with(
            mock.ANY, self._instance, self._network_values, 1)

    @mock.patch.object(vif, 'get_network_device', return_value='device')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'get_network_detach_config_spec',
                       return_value='fake-detach-spec')
    @mock.patch.object(vm_util, 'get_vm_detach_port_index', return_value=1)
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def test_detach_interface(self, mock_get_vm_ref,
                              mock_get_detach_port_index,
                              mock_get_network_detach_config_spec,
                              mock_reconfigure_vm,
                              mock_get_network_device):
        _network_api = mock.Mock()
        self._vmops._network_api = _network_api

        with mock.patch.object(self._session, '_call_method',
                               return_value='hardware-devices'):
            self._vmops.detach_interface(self._context, self._instance,
                                         self._network_values)
        mock_get_vm_ref.assert_called_once_with(self._session, self._instance)
        mock_get_detach_port_index.assert_called_once_with(self._session,
                                                           'fake-ref', None)
        mock_get_network_detach_config_spec.assert_called_once_with(
            self._session.vim.client.factory, 'device', 1)
        mock_reconfigure_vm.assert_called_once_with(self._session,
                                                    'fake-ref',
                                                    'fake-detach-spec')
        _network_api.update_instance_vnic_index.assert_called_once_with(
            mock.ANY, self._instance, self._network_values, None)

    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def test_get_mks_console(self, mock_get_vm_ref):
        ticket = mock.MagicMock()
        ticket.host = 'esx1'
        ticket.port = 902
        ticket.ticket = 'fira'
        ticket.sslThumbprint = 'aa:bb:cc:dd:ee:ff'
        ticket.cfgFile = '[ds1] fira/foo.vmx'
        with mock.patch.object(self._session, '_call_method',
                               return_value=ticket):
            console = self._vmops.get_mks_console(self._instance)
            self.assertEqual('esx1', console.host)
            self.assertEqual(902, console.port)
            path = jsonutils.loads(console.internal_access_path)
            self.assertEqual('fira', path['ticket'])
            self.assertEqual('aabbccddeeff', path['thumbprint'])
            self.assertEqual('[ds1] fira/foo.vmx', path['cfgFile'])

    def test_get_cores_per_socket(self):
        extra_specs = {'hw:cpu_sockets': 7}
        flavor = objects.Flavor(name='m1.small',
                                memory_mb=6,
                                vcpus=28,
                                root_gb=496,
                                ephemeral_gb=8128,
                                swap=33550336,
                                extra_specs=extra_specs)
        extra_specs = self._vmops._get_extra_specs(flavor, None)
        self.assertEqual(4, int(extra_specs.cores_per_socket))

    def test_get_folder_name(self):
        uuid = uuidutils.generate_uuid()
        name = 'fira'
        expected = 'fira (%s)' % uuid
        folder_name = self._vmops._get_folder_name(name, uuid)
        self.assertEqual(expected, folder_name)

        name = 'X' * 255
        expected = '%s (%s)' % ('X' * 40, uuid)
        folder_name = self._vmops._get_folder_name(name, uuid)
        self.assertEqual(expected, folder_name)
        self.assertEqual(79, len(folder_name))

    @mock.patch.object(vmops.VMwareVMOps, '_get_extra_specs')
    @mock.patch.object(vm_util, 'reconfigure_vm')
    @mock.patch.object(vm_util, 'get_network_attach_config_spec',
                       return_value='fake-attach-spec')
    @mock.patch.object(vm_util, 'get_attach_port_index', return_value=1)
    @mock.patch.object(vm_util, 'get_vm_ref', return_value='fake-ref')
    def test_attach_interface_with_limits(self, mock_get_vm_ref,
                              mock_get_attach_port_index,
                              mock_get_network_attach_config_spec,
                              mock_reconfigure_vm,
                              mock_extra_specs):
        _network_api = mock.Mock()
        self._vmops._network_api = _network_api

        vif_info = vif.get_vif_dict(self._session, self._cluster,
                                    'VirtualE1000', self._network_values)
        vif_limits = vm_util.Limits(shares_level='custom',
                                    shares_share=40)
        extra_specs = vm_util.ExtraSpecs(vif_limits=vif_limits)
        mock_extra_specs.return_value = extra_specs
        self._vmops.attach_interface(self._context, self._instance,
                                     self._image_meta,
                                     self._network_values)
        mock_get_vm_ref.assert_called_once_with(self._session, self._instance)
        mock_get_attach_port_index.assert_called_once_with(self._session,
                                                           'fake-ref')
        mock_get_network_attach_config_spec.assert_called_once_with(
            self._session.vim.client.factory, vif_info, 1,
            extra_specs.vif_limits)
        mock_reconfigure_vm.assert_called_once_with(self._session,
                                                    'fake-ref',
                                                    'fake-attach-spec')
        _network_api.update_instance_vnic_index.assert_called_once_with(
            mock.ANY, self._instance, self._network_values, 1)
