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
import copy

from nova import objects
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_in_placement as base


class PCIInPlacementCreateAfterDeleteTestCase(base.PlacementPCIReportingTests):
    def setUp(self):
        super().setUp()
        self.flags(group='filter_scheduler', pci_in_placement=True)

    def test_create_after_delete(self):
        device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        )
        pci_alias = {
            "name": "a-vf",
            "product_id": fakelibvirt.VF_PROD_ID,
            "vendor_id": fakelibvirt.PCI_VEND_ID,
        }
        self._test_create_second_vm_after_first_is_deleted(
            device_spec, pci_alias, self.VF_RC, traits=[])

    def test_create_after_delete_with_rc_and_traits(self):
        device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "resource_class": "vf",
                    "traits": "blue,big",
                },
            ]
        )
        pci_alias = {
            "name": "a-vf",
            "resource_class": "vf",
            "traits": "big",
        }
        self._test_create_second_vm_after_first_is_deleted(
            device_spec, pci_alias,
            "CUSTOM_VF", traits=["CUSTOM_BLUE", "CUSTOM_BIG"])

    def _test_create_second_vm_after_first_is_deleted(
        self, device_spec, pci_alias, rc, traits
    ):
        # The fake libvirt will emulate on the host:
        # * one PF with 2 VFs
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # make the VFs available
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {rc: 2},
            },
            "traits": {"0000:81:00.0": traits,
            },
            "usages": {
                "0000:81:00.0": {rc: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assertPCIDeviceCounts('compute1', total=2, free=2)
        # assert that the two VFs from the same PF are in the same pool
        pools = objects.ComputeNode.get_first_node_by_host_for_old_compat(
            self.ctxt, "compute1").pci_device_pools
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0].count, 2)
        compute1_empty = copy.deepcopy(compute1_expected_placement_view)

        self.flags(
            group="pci",
            alias=self._to_list_of_json_str([pci_alias]),
        )
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_1vf = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts('compute1', total=2, free=1)
        compute1_expected_placement_view["usages"] = {
            "0000:81:00.0": {rc: 1}
        }
        compute1_expected_placement_view["allocations"][server_1vf["id"]] = {
            "0000:81:00.0": {rc: 1},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assert_no_pci_healing("compute1")

        self._delete_server(server_1vf)
        self.assertPCIDeviceCounts('compute1', total=2, free=2)
        self.assert_placement_pci_view("compute1", **compute1_empty)

        # This is already shows the potential issue behind bug/2098496.
        # After the server is deleted we are not back to a single pool of 2
        # VFs but instead two separate pools with one device each but both
        # related to the same rp_uuid. This breaks an assumption of the pool
        # allocation logic later.
        pools = objects.ComputeNode.get_first_node_by_host_for_old_compat(
            self.ctxt, "compute1").pci_device_pools
        self.assertEqual(len(pools), 2)
        self.assertEqual(pools[0].count, 1)
        self.assertEqual(pools[1].count, 1)
        self.assertEqual(pools[0].tags['rp_uuid'], pools[1].tags['rp_uuid'])

        # This is the expected state after the bug is fixed
        # assert that the single pool is not broken into two during the
        # de-allocation
        # pools = objects.ComputeNode.get_first_node_by_host_for_old_compat(
        #     self.ctxt, "compute1").pci_device_pools
        # self.assertEqual(len(pools), 1)
        # self.assertEqual(pools[0].count, 2)

        server_1vf = self._create_server(flavor_id=flavor_id, networks=[])
        # This is bug/2098496 as the VM now consumes 2 VFs instead of one it
        # requested
        self.assertPCIDeviceCounts('compute1', total=2, free=0)
        compute1_expected_placement_view = copy.deepcopy(compute1_empty)
        compute1_expected_placement_view["usages"] = {
            "0000:81:00.0": {rc: 2}
        }
        compute1_expected_placement_view["allocations"][server_1vf["id"]] = {
            "0000:81:00.0": {rc: 2},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        # prove that the placement view got corrupted only after the claim
        # on the compute due the allocation healing logic
        last_healing = self.pci_healing_fixture.last_healing("compute1")
        alloc_before = last_healing[0]
        alloc_after = last_healing[1]

        def alloc_by_rc(allocations, rc):
            return [
                alloc["resources"][rc]
                for alloc in allocations.values()
                if rc in alloc["resources"]
            ]

        pci_alloc_before = alloc_by_rc(
            alloc_before[server_1vf["id"]]["allocations"], rc)
        self.assertEqual(1, sum(pci_alloc_before))

        pci_alloc_after = alloc_by_rc(
            alloc_after[server_1vf["id"]]["allocations"], rc)
        self.assertEqual(2, sum(pci_alloc_after))

        # This is the expected result after the bug is fixed
        # self.assertPCIDeviceCounts('compute1', total=2, free=1)
        # compute1_expected_placement_view = copy.deepcopy(compute1_empty)
        # compute1_expected_placement_view["usages"] = {
        #     "0000:81:00.0": {rc: 1}
        # }
        # compute1_expected_placement_view["allocations"][server_1vf["id"]] = {
        #     "0000:81:00.0": {rc: 1},
        # }
        # self.assert_placement_pci_view(
        #     "compute1", **compute1_expected_placement_view)
        # self.assert_no_pci_healing("compute1")
