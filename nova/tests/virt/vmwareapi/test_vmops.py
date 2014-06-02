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
import contextlib
import copy

import mock

from nova.compute import power_state
from nova import context
from nova import exception
from nova.network import model as network_model
from nova.objects import instance as instance_obj
from nova import test
from nova.tests import fake_instance
import nova.tests.image.fake
from nova.tests.virt.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops


class VMwareVMOpsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMOpsTestCase, self).setUp()
        vmwareapi_fake.reset()
        stubs.set_stubs(self.stubs)
        self.flags(image_cache_subdirectory_name='vmware_base',
                   my_ip='')
        self._context = context.RequestContext('fake_user', 'fake_project')
        self._session = driver.VMwareAPISession()

        self._virtapi = mock.Mock()
        self._vmops = vmops.VMwareVMOps(self._session, self._virtapi, None)
        self._image_id = nova.tests.image.fake.get_valid_image_id()
        values = {
            'name': 'fake_name',
            'uuid': 'fake_uuid',
            'vcpus': 1,
            'memory_mb': 512,
            'image_ref': self._image_id,
            'root_gb': 1,
            'node': 'respool-1001(MyResPoolName)',
        }
        self._context = context.RequestContext('fake_user', 'fake_project')
        self._instance = fake_instance.fake_instance_obj(self._context,
                                                         **values)

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
        self.network_info = network_model.NetworkInfo([
                network_model.VIF(id=None,
                                  address='DE:AD:BE:EF:00:00',
                                  network=network,
                                  type=None,
                                  devname=None,
                                  ovs_interfaceid=None,
                                  rxtx_cap=3)
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

    def test_get_disk_format_none(self):
        format, is_iso = self._vmops._get_disk_format({'disk_format': None})
        self.assertIsNone(format)
        self.assertFalse(is_iso)

    def test_get_disk_format_iso(self):
        format, is_iso = self._vmops._get_disk_format({'disk_format': 'iso'})
        self.assertEqual('iso', format)
        self.assertTrue(is_iso)

    def test_get_disk_format_bad(self):
        self.assertRaises(exception.InvalidDiskFormat,
                          self._vmops._get_disk_format,
                          {'disk_format': 'foo'})

    def test_get_machine_id_str(self):
        result = vmops.VMwareVMOps._get_machine_id_str(self.network_info)
        self.assertEqual(result,
                         'DE:AD:BE:EF:00:00;192.168.0.100;255.255.255.0;'
                         '192.168.0.1;192.168.0.255;192.168.0.1#')
        result = vmops.VMwareVMOps._get_machine_id_str(
                                        self.pure_IPv6_network_info)
        self.assertEqual('DE:AD:BE:EF:00:00;;;;;#', result)

    def test_use_linked_clone_override_nf(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, False)
        self.assertFalse(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_none_true(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, True)
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ny(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, "yes")
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ft(self):
        value = vmops.VMwareVMOps.decide_linked_clone(False, True)
        self.assertFalse(value,
                        "image level metadata failed to override global")

    def test_use_linked_clone_override_no_true(self):
        value = vmops.VMwareVMOps.decide_linked_clone("no", True)
        self.assertFalse(value,
                        "image level metadata failed to override global")

    def test_use_linked_clone_override_yf(self):
        value = vmops.VMwareVMOps.decide_linked_clone("yes", False)
        self.assertTrue(value,
                        "image level metadata failed to override global")

    def _setup_create_folder_mocks(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        base_name = 'folder'
        ds_name = "datastore"
        ds_ref = mock.Mock()
        ds_ref.value = 1
        dc_ref = mock.Mock()
        ops._datastore_dc_mapping[ds_ref.value] = vmops.DcInfo(
                ref=dc_ref,
                name='fake-name',
                vmFolder='fake-folder')
        path = ds_util.build_datastore_path(ds_name, base_name)
        ds_util.mkdir = mock.Mock()
        return ds_name, ds_ref, ops, path, dc_ref

    def test_create_folder_if_missing(self):
        ds_name, ds_ref, ops, path, dc = self._setup_create_folder_mocks()
        ops._create_folder_if_missing(ds_name, ds_ref, 'folder')
        ds_util.mkdir.assert_called_with(ops._session, path, dc)

    def test_create_folder_if_missing_exception(self):
        ds_name, ds_ref, ops, path, dc = self._setup_create_folder_mocks()
        ds_util.mkdir.side_effect = error_util.FileAlreadyExistsException()
        ops._create_folder_if_missing(ds_name, ds_ref, 'folder')
        ds_util.mkdir.assert_called_with(ops._session, path, dc)

    @mock.patch.object(ds_util, 'file_exists', return_value=True)
    def test_check_if_folder_file_exists_with_existing(self,
                                                       mock_exists):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        ops._create_folder_if_missing = mock.Mock()
        mock_ds_ref = mock.Mock()
        ops._check_if_folder_file_exists(mock.Mock(), mock_ds_ref, "datastore",
                                         "folder", "some_file")
        ops._create_folder_if_missing.assert_called_once_with('datastore',
                                                              mock_ds_ref,
                                                              'vmware_base')

    @mock.patch.object(ds_util, 'file_exists', return_value=False)
    def test_check_if_folder_file_exists_no_existing(self, mock_exists):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        ops._create_folder_if_missing = mock.Mock()
        mock_ds_ref = mock.Mock()
        ops._check_if_folder_file_exists(mock.Mock(), mock_ds_ref, "datastore",
                                         "folder", "some_file")
        ops._create_folder_if_missing.assert_called_once_with('datastore',
                                                              mock_ds_ref,
                                                              'vmware_base')

    def test_get_valid_vms_from_retrieve_result(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        fake_objects = vmwareapi_fake.FakeRetrieveResult()
        fake_objects.add_object(vmwareapi_fake.VirtualMachine())
        fake_objects.add_object(vmwareapi_fake.VirtualMachine())
        fake_objects.add_object(vmwareapi_fake.VirtualMachine())
        vms = ops._get_valid_vms_from_retrieve_result(fake_objects)
        self.assertEqual(3, len(vms))

    def test_get_valid_vms_from_retrieve_result_with_invalid(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        fake_objects = vmwareapi_fake.FakeRetrieveResult()
        fake_objects.add_object(vmwareapi_fake.VirtualMachine())
        invalid_vm1 = vmwareapi_fake.VirtualMachine()
        invalid_vm1.set('runtime.connectionState', 'orphaned')
        invalid_vm2 = vmwareapi_fake.VirtualMachine()
        invalid_vm2.set('runtime.connectionState', 'inaccessible')
        fake_objects.add_object(invalid_vm1)
        fake_objects.add_object(invalid_vm2)
        vms = ops._get_valid_vms_from_retrieve_result(fake_objects)
        self.assertEqual(1, len(vms))

    def test_delete_vm_snapshot(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('RemoveSnapshot_Task', method)
            self.assertEqual(args[0], "fake_vm_snapshot")
            self.assertEqual(kwargs['removeChildren'], False)
            self.assertEqual(kwargs['consolidate'], True)
            return 'fake_remove_snapshot_task'

        with contextlib.nested(
            mock.patch.object(self._session, '_wait_for_task'),
            mock.patch.object(self._session, '_call_method', fake_call_method)
        ) as (_wait_for_task, _call_method):
            self._vmops._delete_vm_snapshot(self._instance,
                                            "fake_vm_ref", "fake_vm_snapshot")
            _wait_for_task.assert_has_calls([
                   mock.call('fake_remove_snapshot_task')])

    def test_create_vm_snapshot(self):

        method_list = ['CreateSnapshot_Task', 'get_dynamic_property']

        def fake_call_method(module, method, *args, **kwargs):
            expected_method = method_list.pop(0)
            self.assertEqual(expected_method, method)
            if (expected_method == 'CreateSnapshot_Task'):
                self.assertEqual(args[0], "fake_vm_ref")
                self.assertEqual(kwargs['memory'], False)
                self.assertEqual(kwargs['quiesce'], True)
                return 'fake_snapshot_task'
            elif (expected_method == 'get_dynamic_property'):
                task_info = mock.Mock()
                task_info.result = "fake_snapshot_ref"
                self.assertEqual(('fake_snapshot_task', 'Task', 'info'), args)
                return task_info

        with contextlib.nested(
            mock.patch.object(self._session, '_wait_for_task'),
            mock.patch.object(self._session, '_call_method', fake_call_method)
        ) as (_wait_for_task, _call_method):
            snap = self._vmops._create_vm_snapshot(self._instance,
                                                   "fake_vm_ref")
            self.assertEqual("fake_snapshot_ref", snap)
            _wait_for_task.assert_has_calls([
                   mock.call('fake_snapshot_task')])

    def test_update_instance_progress(self):
        instance = instance_obj.Instance(context=mock.MagicMock(),
                                         uuid='fake-uuid')
        with mock.patch.object(instance, 'save') as mock_save:
            self._vmops._update_instance_progress(instance._context,
                                                  instance, 5, 10)
            mock_save.assert_called_once_with()
        self.assertEqual(50, instance.progress)

    @mock.patch('nova.virt.vmwareapi.vm_util.get_vm_ref',
                return_value='fake_ref')
    def test_get_info(self, mock_get_vm_ref):
        props = ['summary.config.numCpu', 'summary.config.memorySizeMB',
                 'runtime.powerState']
        prop_cpu = vmwareapi_fake.Prop(props[0], 4)
        prop_mem = vmwareapi_fake.Prop(props[1], 128)
        prop_state = vmwareapi_fake.Prop(props[2], 'poweredOn')
        prop_list = [prop_state, prop_mem, prop_cpu]
        obj_content = vmwareapi_fake.ObjectContent(None, prop_list=prop_list)
        result = vmwareapi_fake.FakeRetrieveResult()
        result.add_object(obj_content)
        mock_call_method = mock.Mock(return_value=result)
        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            info = self._vmops.get_info(self._instance)
            mock_call_method.assert_called_once_with(vim_util,
                'get_object_properties', None, 'fake_ref', 'VirtualMachine',
                props)
            mock_get_vm_ref.assert_called_once_with(self._session,
                self._instance)
            self.assertEqual(power_state.RUNNING, info['state'])
            self.assertEqual(128 * 1024, info['max_mem'])
            self.assertEqual(128 * 1024, info['mem'])
            self.assertEqual(4, info['num_cpu'])
            self.assertEqual(0, info['cpu_time'])

    def _test_get_datacenter_ref_and_name(self, ds_ref_exists=False):
        instance_ds_ref = mock.Mock()
        instance_ds_ref.value = "ds-1"
        _vcvmops = vmops.VMwareVCVMOps(self._session, None, None)
        if ds_ref_exists:
            ds_ref = mock.Mock()
            ds_ref.value = "ds-1"
        else:
            ds_ref = None

        def fake_call_method(module, method, *args, **kwargs):
            fake_object1 = vmwareapi_fake.FakeRetrieveResult()
            fake_object1.add_object(vmwareapi_fake.Datacenter(
                ds_ref=ds_ref))
            if not ds_ref:
                # Token is set for the fake_object1, so it will continue to
                # fetch the next object.
                setattr(fake_object1, 'token', 'token-0')
                if method == "continue_to_get_objects":
                    fake_object2 = vmwareapi_fake.FakeRetrieveResult()
                    fake_object2.add_object(vmwareapi_fake.Datacenter())
                    return fake_object2

            return fake_object1

        with mock.patch.object(self._session, '_call_method',
                               side_effect=fake_call_method) as fake_call:
            dc_info = _vcvmops.get_datacenter_ref_and_name(instance_ds_ref)

            if ds_ref:
                self.assertEqual(1, len(_vcvmops._datastore_dc_mapping))
                fake_call.assert_called_once_with(vim_util, "get_objects",
                    "Datacenter", ["name", "datastore", "vmFolder"])
                self.assertEqual("ha-datacenter", dc_info.name)
            else:
                calls = [mock.call(vim_util, "get_objects", "Datacenter",
                                   ["name", "datastore", "vmFolder"]),
                         mock.call(vim_util, "continue_to_get_objects",
                                   "token-0")]
                fake_call.assert_has_calls(calls)
                self.assertIsNone(dc_info)

    def test_get_datacenter_ref_and_name(self):
        self._test_get_datacenter_ref_and_name(ds_ref_exists=True)

    def test_get_datacenter_ref_and_name_with_no_datastore(self):
        self._test_get_datacenter_ref_and_name()

    def test_unrescue_power_on(self):
        self._test_unrescue(True)

    def test_unrescue_power_off(self):
        self._test_unrescue(False)

    def _test_unrescue(self, power_on):
        self._vmops._volumeops = mock.Mock()
        vm_rescue_ref = mock.Mock()
        vm_ref = mock.Mock()

        args_list = [(vm_ref, 'VirtualMachine',
                      'config.hardware.device'),
                     (vm_rescue_ref, 'VirtualMachine',
                      'config.hardware.device')]

        def fake_call_method(module, method, *args, **kwargs):
            expected_args = args_list.pop(0)
            self.assertEqual('get_dynamic_property', method)
            self.assertEqual(expected_args, args)

        path = mock.Mock()
        path_and_type = (path, mock.Mock(), mock.Mock())
        r_instance = copy.deepcopy(self._instance)
        with contextlib.nested(
                mock.patch.object(vm_util, 'get_vmdk_path_and_adapter_type',
                                  return_value=path_and_type),
                mock.patch.object(vm_util, 'get_vmdk_volume_disk'),
                mock.patch.object(vm_util, 'power_on_instance'),
                mock.patch.object(vm_util, 'get_vm_ref', return_value=vm_ref),
                mock.patch.object(vm_util, 'get_vm_ref_from_name',
                                  return_value=vm_rescue_ref),
                mock.patch.object(self._session, '_call_method',
                                  fake_call_method),
                mock.patch.object(self._vmops, '_power_off_vm_ref'),
                mock.patch.object(self._vmops, '_destroy_instance'),
                mock.patch.object(copy, 'deepcopy', return_value=r_instance)
        ) as (_get_vmdk_path_and_adapter_type, _get_vmdk_volume_disk,
              _power_on_instance, _get_vm_ref, _get_vm_ref_from_name,
              _call_method, _power_off, _destroy_instance, _deep_copy):
            self._vmops.unrescue(self._instance, power_on=power_on)

            _get_vmdk_path_and_adapter_type.assert_called_once_with(
                None, uuid='fake_uuid')
            _get_vmdk_volume_disk.assert_called_once_with(None, path=path)
            if power_on:
                _power_on_instance.assert_called_once_with(self._session,
                                                           self._instance,
                                                           vm_ref=vm_ref)
            else:
                self.assertFalse(_power_on_instance.called)
            _get_vm_ref.assert_called_once_with(self._session,
                                                self._instance)
            _get_vm_ref_from_name.assert_called_once_with(self._session,
                                                          'fake_uuid-rescue')
            _power_off.assert_called_once_with(vm_rescue_ref)
            _destroy_instance.assert_called_once_with(r_instance, None,
                instance_name='fake_uuid-rescue')

    def _test_finish_migration(self, power_on=True, resize_instance=False):
        """Tests the finish_migration method on vmops."""
        with contextlib.nested(
                mock.patch.object(self._session, "_call_method",
                                  return_value='fake-task'),
                mock.patch.object(self._vmops, "_update_instance_progress"),
                mock.patch.object(self._session, "_wait_for_task"),
                mock.patch.object(vm_util, "get_vm_resize_spec",
                                  return_value='fake-spec'),
                mock.patch.object(vm_util, "power_on_instance")
        ) as (fake_call_method, fake_update_instance_progress,
              fake_wait_for_task, fake_vm_resize_spec, fake_power_on):
            self._vmops.finish_migration(context=self._context,
                                         migration=None,
                                         instance=self._instance,
                                         disk_info=None,
                                         network_info=None,
                                         block_device_info=None,
                                         resize_instance=resize_instance,
                                         image_meta=None,
                                         power_on=power_on)
            if resize_instance:
                fake_vm_resize_spec.assert_called_once_with(
                    self._session._get_vim().client.factory,
                    self._instance)
                fake_call_method.assert_has_calls(mock.call(
                    self._session._get_vim(),
                    "ReconfigVM_Task",
                    'f',
                    spec='fake-spec'))
                fake_wait_for_task.assert_called_once_with('fake-task')
            else:
                self.assertFalse(fake_vm_resize_spec.called)
                self.assertFalse(fake_wait_for_task.called)

            if power_on:
                fake_power_on.assert_called_once_with(self._session,
                                                      self._instance,
                                                      vm_ref='f')
            else:
                self.assertFalse(fake_power_on.called)
            fake_update_instance_progress.called_once_with(
                self._context, self._instance, 4, vmops.RESIZE_TOTAL_STEPS)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(power_on=True, resize_instance=False)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(power_on=False, resize_instance=False)

    def test_finish_migration_power_on_resize(self):
        self._test_finish_migration(power_on=True, resize_instance=True)

    @mock.patch.object(vm_util, 'associate_vmref_for_instance')
    @mock.patch.object(vm_util, 'power_on_instance')
    def _test_finish_revert_migration(self, fake_power_on,
                                      fake_associate_vmref, power_on):
        """Tests the finish_revert_migration method on vmops."""

        # setup the test instance in the database
        self._vmops.finish_revert_migration(self._context,
                                                 instance=self._instance,
                                                 network_info=None,
                                                 block_device_info=None,
                                                 power_on=power_on)
        fake_associate_vmref.assert_called_once_with(self._session,
                                                     self._instance,
                                                     suffix='-orig')
        if power_on:
            fake_power_on.assert_called_once_with(self._session,
                                                  self._instance)
        else:
            self.assertFalse(fake_power_on.called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(power_on=True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(power_on=False)

    def test_spawn_mask_block_device_info_password(self):
        # Very simple test that just ensures block_device_info auth_password
        # is masked when logged; the rest of the test just fails out early.
        data = {'auth_password': 'scrubme'}
        bdm = [{'connection_info': {'data': data}}]
        bdi = {'block_device_mapping': bdm}

        # Tests that the parameters to the to_xml method are sanitized for
        # passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.assertNotIn('scrubme', args[0])

        with mock.patch.object(vmops.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            # the invalid disk format will cause an exception
            image_meta = {'disk_format': 'fake'}
            self.assertRaises(exception.InvalidDiskFormat, self._vmops.spawn,
                              self._context, self._instance, image_meta,
                              injected_files=None, admin_password=None,
                              network_info=[], block_device_info=bdi)
            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)

    def test_get_ds_browser(self):
        cache = self._vmops._datastore_browser_mapping
        ds_browser = mock.Mock()
        moref = vmwareapi_fake.ManagedObjectReference('datastore-100')
        self.assertIsNone(cache.get(moref.value))
        mock_call_method = mock.Mock(return_value=ds_browser)
        with mock.patch.object(self._session, '_call_method',
                               mock_call_method):
            ret = self._vmops._get_ds_browser(moref)
            mock_call_method.assert_called_once_with(vim_util,
                'get_dynamic_property', moref, 'Datastore', 'browser')
            self.assertIs(ds_browser, ret)
            self.assertIs(ds_browser, cache.get(moref.value))
