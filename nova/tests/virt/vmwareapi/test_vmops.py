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

from nova.network import model as network_model
from nova import test
from nova import utils
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops


class VMwareVMOpsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMOpsTestCase, self).setUp()
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

    def _setup_create_cache_mocks(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        base_name = ops._base_folder
        ds_name = "datastore"
        ds_ref = mock.Mock()
        path = vm_util.build_datastore_path(ds_name, base_name)
        ops._mkdir = mock.Mock()
        return ds_name, ds_ref, ops, path

    def test_create_cache_folder(self):
        ds_name, ds_ref, ops, path = self._setup_create_cache_mocks()
        ops.create_cache_folder(ds_name, ds_ref)
        ops._mkdir.assert_called_with(path, ds_ref)

    def test_create_cache_folder_with_exception(self):
        ds_name, ds_ref, ops, path = self._setup_create_cache_mocks()
        ops._mkdir.side_effect = error_util.FileAlreadyExistsException()
        ops.create_cache_folder(ds_name, ds_ref)
        # assert that the
        ops._mkdir.assert_called_with(path, ds_ref)

    def test_check_if_folder_file_exists_with_existing(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        ops.create_cache_folder = mock.Mock()
        ops._file_exists = mock.Mock()
        ops._file_exists.return_value = True
        ops._check_if_folder_file_exists(mock.Mock(), "datastore",
                                         "folder", "some_file")
        ops.create_cache_folder.assert_called_once()

    def test_check_if_folder_file_exists_no_existing(self):
        ops = vmops.VMwareVMOps(mock.Mock(), mock.Mock(), mock.Mock())
        ops.create_cache_folder = mock.Mock()
        ops._file_exists = mock.Mock()
        ops._file_exists.return_value = True
        ops._check_if_folder_file_exists(mock.Mock(), "datastore",
                                         "folder", "some_file")
        ops.create_cache_folder.assert_called_once()
