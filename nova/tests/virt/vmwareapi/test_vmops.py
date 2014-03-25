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
import mock

import contextlib
import mock

from nova import exception
from nova.network import model as network_model
from nova import test
from nova.tests.virt.vmwareapi import stubs
from nova import utils
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vmops


class VMwareVMOpsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMOpsTestCase, self).setUp()
        vmwareapi_fake.reset()
        stubs.set_stubs(self.stubs)
        self._session = driver.VMwareAPISession()

        self._vmops = vmops.VMwareVMOps(self._session, None, None)
        self._instance = {'name': 'fake_name', 'uuid': 'fake_uuid'}

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
        utils.reset_is_neutron()

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

    def test_is_neutron_nova(self):
        self.flags(network_api_class='nova.network.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertFalse(ops._is_neutron)

    def test_is_neutron_neutron(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertTrue(ops._is_neutron)

    def test_is_neutron_quantum(self):
        self.flags(network_api_class='nova.network.quantumv2.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertTrue(ops._is_neutron)

    def test_use_linked_clone_override_nf(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, False)
        self.assertFalse(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_nt(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, True)
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ny(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, "yes")
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ft(self):
        value = vmops.VMwareVMOps.decide_linked_clone(False, True)
        self.assertFalse(value,
                        "image level metadata failed to override global")

    def test_use_linked_clone_override_nt(self):
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
        ops._check_if_folder_file_exists(mock.Mock(), mock.Mock(), "datastore",
                                         "folder", "some_file")
        ops._create_folder_if_missing.assert_called_once()

    @mock.patch.object(ds_util, 'file_exists', return_value=False)
    def test_check_if_folder_file_exists_no_existing(self, mock_exists):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        ops._create_folder_if_missing = mock.Mock()
        ops._check_if_folder_file_exists(mock.Mock(), mock.Mock(), "datastore",
                                         "folder", "some_file")
        ops._create_folder_if_missing.assert_called_once()

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
