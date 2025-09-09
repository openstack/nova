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
import ddt
import os_traits
from oslo_utils.fixture import uuidsentinel as uuids
from unittest import mock

from nova.compute import pci_placement_translator as ppt
from nova.compute import provider_tree
from nova import exception
from nova.objects import fields
from nova.objects import pci_device
from nova.pci import devspec
from nova import test


def dev(v, p):
    return pci_device.PciDevice(vendor_id=v, product_id=p)


# NOTE(gibi): Most of the nova.compute.pci_placement_translator module is
# covered with functional tests in
# nova.tests.functional.libvirt.test_pci_in_placement
@ddt.ddt
class TestTranslator(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch(
            "nova.compute.pci_placement_translator."
            "_is_placement_tracking_enabled")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_translator_skips_devices_without_matching_spec(self):
        """As every PCI device in the PciTracker is created by matching a
        PciDeviceSpec the translator should always be able to look up the spec
        for a device. But if cannot then the device will be skipped and warning
        will be emitted.
        """
        pci_tracker = mock.Mock()
        pci_tracker.pci_devs = pci_device.PciDeviceList(
            objects=[
                pci_device.PciDevice(
                    address="0000:81:00.0",
                    status=fields.PciDeviceStatus.AVAILABLE,
                    instance_uuid=None,
                )
            ]
        )
        # So we have a device but there is no spec for it
        pci_tracker.dev_filter.get_devspec = mock.Mock(return_value=None)
        pci_tracker.dev_filter.specs = []
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)

        with mock.patch.object(pt, "remove", new=mock.NonCallableMock()):
            ppt.update_provider_tree_for_pci(
                pt, "fake-node", pci_tracker, {}, [])

        self.assertIn(
            "WARNING [nova.compute.pci_placement_translator] "
            "Device spec is not found for device 0000:81:00.0 in "
            "[pci]device_spec. Ignoring device in Placement resource view. "
            "This should not happen. Please file a bug.",
            self.stdlog.logger.output
        )

    @ddt.unpack
    @ddt.data(
        (None, set()),
        ("", set()),
        ("a", {"CUSTOM_A"}),
        ("a,b", {"CUSTOM_A", "CUSTOM_B"}),
        ("HW_GPU_API_VULKAN", {"HW_GPU_API_VULKAN"}),
        ("CUSTOM_FOO", {"CUSTOM_FOO"}),
        ("custom_bar", {"CUSTOM_BAR"}),
        ("custom-bar", {"CUSTOM_CUSTOM_BAR"}),
        ("CUSTOM_a", {"CUSTOM_A"}),
        ("a@!#$b123X", {"CUSTOM_A_B123X"}),
        # Note that both trait names are normalized to the same trait
        ("a!@b,a###b", {"CUSTOM_A_B"}),
    )
    def test_trait_normalization(self, trait_names, expected_traits):
        self.assertEqual(
            expected_traits,
            ppt.get_traits(trait_names)
        )

    @ddt.unpack
    @ddt.data(
        (dev(v='1234', p='5678'), None, "CUSTOM_PCI_1234_5678"),
        (dev(v='1234', p='5678'), "", "CUSTOM_PCI_1234_5678"),
        (dev(v='1234', p='5678'), "PGPU", "PGPU"),
        (dev(v='1234', p='5678'), "pgpu", "PGPU"),
        (dev(v='1234', p='5678'), "foobar", "CUSTOM_FOOBAR"),
        (dev(v='1234', p='5678'), "custom_foo", "CUSTOM_FOO"),
        (dev(v='1234', p='5678'), "CUSTOM_foo", "CUSTOM_FOO"),
        (dev(v='1234', p='5678'), "custom_FOO", "CUSTOM_FOO"),
        (dev(v='1234', p='5678'), "CUSTOM_FOO", "CUSTOM_FOO"),
        (dev(v='1234', p='5678'), "custom-foo", "CUSTOM_CUSTOM_FOO"),
        (dev(v='1234', p='5678'), "a###b", "CUSTOM_A_B"),
        (dev(v='123a', p='567b'), "", "CUSTOM_PCI_123A_567B"),
    )
    def test_resource_class_normalization(self, pci_dev, rc_name, expected_rc):
        self.assertEqual(
            expected_rc,
            ppt.get_resource_class(
                rc_name, pci_dev.vendor_id, pci_dev.product_id
            ),
        )

    def test_dependent_device_pf_then_vf(self):
        pv = ppt.PlacementView(
            "fake-node", instances_under_same_host_resize=[])
        pf = pci_device.PciDevice(
            address="0000:81:00.0",
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
        )
        vf = pci_device.PciDevice(
            address="0000:81:00.1",
            parent_addr=pf.address,
            dev_type=fields.PciDeviceType.SRIOV_VF,
            vendor_id="dead",
            product_id="beef",
        )

        pv._add_dev(pf, {"resource_class": "foo"})
        ex = self.assertRaises(
            exception.PlacementPciDependentDeviceException,
            pv._add_dev,
            vf,
            {"resource_class": "bar"}
        )

        self.assertEqual(
            "Configuring both 0000:81:00.1 and 0000:81:00.0 in "
            "[pci]device_spec is not supported. Either the parent PF or its "
            "children VFs can be configured.",
            str(ex),
        )

    def test_dependent_device_vf_then_pf(self):
        pv = ppt.PlacementView(
            "fake-node", instances_under_same_host_resize=[])
        pf = pci_device.PciDevice(
            address="0000:81:00.0",
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
        )
        vf = pci_device.PciDevice(
            address="0000:81:00.1",
            parent_addr=pf.address,
            dev_type=fields.PciDeviceType.SRIOV_VF,
            vendor_id="dead",
            product_id="beef",
        )
        vf2 = pci_device.PciDevice(
            address="0000:81:00.2",
            parent_addr=pf.address,
            dev_type=fields.PciDeviceType.SRIOV_VF,
            vendor_id="dead",
            product_id="beef",
        )

        pv._add_dev(vf, {"resource_class": "foo"})
        pv._add_dev(vf2, {"resource_class": "foo"})
        ex = self.assertRaises(
            exception.PlacementPciDependentDeviceException,
            pv._add_dev,
            pf,
            {"resource_class": "bar"}
        )

        self.assertEqual(
            "Configuring both 0000:81:00.0 and 0000:81:00.1,0000:81:00.2 in "
            "[pci]device_spec is not supported. Either the parent PF or its "
            "children VFs can be configured.",
            str(ex),
        )

    def test_mixed_rc_for_sibling_vfs(self):
        pv = ppt.PlacementView(
            "fake-node", instances_under_same_host_resize=[])
        vf1, vf2, vf3, vf4 = [
            pci_device.PciDevice(
                address="0000:81:00.%d" % f,
                parent_addr="0000:71:00.0",
                dev_type=fields.PciDeviceType.SRIOV_VF,
                vendor_id="dead",
                product_id="beef",
            )
            for f in range(0, 4)
        ]

        pv._add_dev(vf1, {"resource_class": "a", "traits": "foo,bar,baz"})
        # order is irrelevant
        pv._add_dev(vf2, {"resource_class": "a", "traits": "foo,baz,bar"})
        # but missing trait is rejected
        ex = self.assertRaises(
            exception.PlacementPciMixedTraitsException,
            pv._add_dev,
            vf3,
            {"resource_class": "a", "traits": "foo,bar"},
        )
        self.assertEqual(
            "VFs from the same PF cannot be configured with different set of "
            "'traits' in [pci]device_spec. We got "
            "COMPUTE_MANAGED_PCI_DEVICE,CUSTOM_BAR,CUSTOM_FOO for "
            "0000:81:00.2 and "
            "COMPUTE_MANAGED_PCI_DEVICE,CUSTOM_BAR,CUSTOM_BAZ,CUSTOM_FOO "
            "for 0000:81:00.0,0000:81:00.1.",
            str(ex),
        )
        # as well as additional trait
        ex = self.assertRaises(
            exception.PlacementPciMixedTraitsException,
            pv._add_dev,
            vf4,
            {"resource_class": "a", "traits": "foo,bar,baz,extra"}
        )
        self.assertEqual(
            "VFs from the same PF cannot be configured with different set of "
            "'traits' in [pci]device_spec. We got "
            "COMPUTE_MANAGED_PCI_DEVICE,CUSTOM_BAR,CUSTOM_BAZ,CUSTOM_EXTRA,"
            "CUSTOM_FOO for 0000:81:00.3 and COMPUTE_MANAGED_PCI_DEVICE,"
            "CUSTOM_BAR,CUSTOM_BAZ,CUSTOM_FOO for 0000:81:00.0,0000:81:00.1.",
            str(ex),
        )

    def test_translator_maps_pci_device_to_rp(self):
        pv = ppt.PlacementView(
            "fake-node", instances_under_same_host_resize=[])
        vf = pci_device.PciDevice(
            address="0000:81:00.1",
            parent_addr="0000:71:00.0",
            dev_type=fields.PciDeviceType.SRIOV_VF,
            vendor_id="dead",
            product_id="beef",
        )
        pf = pci_device.PciDevice(
            address="0000:72:00.0",
            parent_addr=None,
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
        )
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)

        pv._add_dev(vf, {})
        pv._add_dev(pf, {})
        pv.update_provider_tree(pt, {})

        self.assertEqual(
            pt.data("fake-node_0000:71:00.0").uuid, vf.extra_info["rp_uuid"]
        )
        self.assertEqual(
            pt.data("fake-node_0000:72:00.0").uuid, pf.extra_info["rp_uuid"]
        )

    def test_update_provider_tree_for_pci_update_pools(self):
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pf = pci_device.PciDevice(
            address="0000:72:00.0",
            parent_addr=None,
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
            status=fields.PciDeviceStatus.AVAILABLE,
        )
        pci_tracker = mock.Mock()
        pci_tracker.pci_devs = [pf]
        pci_tracker.dev_filter.specs = [devspec.PciDeviceSpec({})]

        ppt.update_provider_tree_for_pci(pt, 'fake-node', pci_tracker, {}, [])

        pci_tracker.stats.populate_pools_metadata_from_assigned_devices.\
            assert_called_once_with()

    def _convert_defaultdict_to_dict(self, d):
        if not isinstance(d, collections.defaultdict):
            return d
        return {k: self._convert_defaultdict_to_dict(v) for k, v in d.items()}

    def test_get_usage_per_rc_and_rp_no_allocations(self):
        actual = ppt.PlacementView.get_usage_per_rc_and_rp({})

        self.assertEqual({}, self._convert_defaultdict_to_dict(actual))

    def test_get_usage_per_rc_and_rp_empty_consumer(self):
        actual = ppt.PlacementView.get_usage_per_rc_and_rp({
            uuids.consumer1: {"allocations": {}}
        })

        self.assertEqual({}, self._convert_defaultdict_to_dict(actual))

    def test_get_usage_per_rc_and_rp(self):
        allocations = {
            uuids.consumer1: {
                "allocations": {
                    uuids.rp1: {
                        "resources": {
                            "RC1": 1,
                            "RC2": 3,
                        },
                    },
                    uuids.rp2: {
                        "resources": {
                            "RC2": 5,
                            "RC3": 1,
                        },
                    },
                },
            },
            uuids.consumer2: {
                "allocations": {
                    uuids.rp2: {
                        "resources": {
                            "RC2": 1,
                            "RC3": 3,
                        },
                    },
                    uuids.rp3: {
                        "resources": {
                            "RC1": 1,
                        },
                    },
                },
            },
            uuids.consumer3: {
                "allocations": {
                    uuids.rp1: {
                        "resources": {
                            "RC2": 3,
                        },
                    },
                },
            },
        }
        actual = ppt.PlacementView.get_usage_per_rc_and_rp(allocations)

        expected = {
            uuids.rp1: {
                "RC1": 1,  # only from consumer1
                "RC2": 6,  # from consumer1 (3) + consumer3 (3)
            },
            uuids.rp2: {
                "RC2": 6,  # from consumer1 (5) + consumer2 (1)
                "RC3": 4,  # from consumer1 (1) + consumer2 (3)
            },
            uuids.rp3: {
                "RC1": 1  # only from consumer2
            },
        }
        self.assertEqual(expected, self._convert_defaultdict_to_dict(actual))

    def test_remove_managed_rps_empty_view(self):
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("no-pci", uuids.compute_rp, uuids.non_pci)

        pv = ppt.PlacementView("fake-node", [])
        pv._remove_managed_rps_from_tree_not_in_view(pt)

        # No changes expected in the tree
        self.assertTrue(pt.exists("fake-node"))
        self.assertTrue(pt.exists("no-pci"))

    def test_remove_managed_rps_new_rp_in_view(self):
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("no-pci", uuids.compute_rp, uuids.non_pci)

        pv = ppt.PlacementView("fake-node", [])
        pf = pci_device.PciDevice(
            address="0000:72:00.0",
            parent_addr=None,
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
            status=fields.PciDeviceStatus.AVAILABLE,
        )

        pv.process_dev(pf, devspec.PciDeviceSpec({}))
        pv._remove_managed_rps_from_tree_not_in_view(pt)

        # No RPs is removed
        self.assertTrue(pt.exists("fake-node"))
        self.assertTrue(pt.exists("no-pci"))

    def test_remove_managed_rps_no_rp_change(self):
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("no-pci", uuids.compute_rp, uuids.non_pci)
        pt.new_child("fake-node_0000:72:00.0", uuids.compute_rp, uuids.pci)
        pt.add_traits(
            "fake-node_0000:72:00.0", os_traits.COMPUTE_MANAGED_PCI_DEVICE)

        pv = ppt.PlacementView("fake-node", [])
        pf = pci_device.PciDevice(
            address="0000:72:00.0",
            parent_addr=None,
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
            status=fields.PciDeviceStatus.AVAILABLE,
        )

        pv.process_dev(pf, devspec.PciDeviceSpec({}))
        pv._remove_managed_rps_from_tree_not_in_view(pt)

        # The existing PCI RP is kept as it exists in the View as well
        self.assertTrue(pt.exists("fake-node"))
        self.assertTrue(pt.exists("no-pci"))
        self.assertTrue(pt.exists("fake-node_0000:72:00.0"))

    def test_remove_managed_rps_rp_removed_from_view(self):
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("no-pci", uuids.compute_rp, uuids.non_pci)
        pt.new_child("fake-node_0000:72:00.0", uuids.compute_rp, uuids.pci)
        pt.add_traits(
            "fake-node_0000:72:00.0", os_traits.COMPUTE_MANAGED_PCI_DEVICE)

        pv = ppt.PlacementView("fake-node", [])
        pv._remove_managed_rps_from_tree_not_in_view(pt)

        self.assertTrue(pt.exists("fake-node"))
        self.assertTrue(pt.exists("no-pci"))
        # The PCI RP is removed as it is not in the View anymore
        self.assertFalse(pt.exists("fake-node_0000:72:00.0"))

    def test_adjust_for_removals_no_allocation_no_adjustment(self):
        rp = ppt.PciResourceProvider("pci")
        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("pci", uuids.compute_rp, uuids.pci)
        usage = {uuids.pci: {}}

        rp._adjust_for_removals_and_held_devices(pt, usage)

        self.assertEqual(0, rp.adjustment)

    def test_adjust_for_removals_allocated_configured_no_adjustment(self):
        rp = ppt.PciResourceProvider("fake-node_0000:72:00.0")
        pf = pci_device.PciDevice(
            address="0000:72:00.0",
            parent_addr=None,
            dev_type=fields.PciDeviceType.SRIOV_PF,
            vendor_id="dead",
            product_id="beef",
            status=fields.PciDeviceStatus.ALLOCATED,
        )
        rp.add_parent(pf, {})

        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("fake-node_0000:72:00.0", uuids.compute_rp, uuids.pci)

        usage = {uuids.pci: {"CUSTOM_PCI_DEAD_BEEF": 1}}

        rp._adjust_for_removals_and_held_devices(pt, usage)

        self.assertEqual(0, rp.adjustment)
        self.assertEqual(1, rp.total)

    def test_adjust_for_removals_allocated_removed(self):
        rp = ppt.PciResourceProvider("fake-node_0000:72:00.0")
        vf = pci_device.PciDevice(
            address="0000:72:00.1",
            parent_addr="0000:72:00.0",
            dev_type=fields.PciDeviceType.SRIOV_VF,
            vendor_id="dead",
            product_id="beef",
            status=fields.PciDeviceStatus.ALLOCATED,
        )
        rp.add_child(vf, {})

        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("fake-node_0000:72:00.0", uuids.compute_rp, uuids.pci)

        # We have two allocations but only one VF left so one VF inventory
        # is missing. We expect an adjustment for that
        usage = {uuids.pci: {"CUSTOM_PCI_DEAD_BEEF": 2}}

        rp._adjust_for_removals_and_held_devices(pt, usage)

        self.assertEqual(1, len(rp.devs))
        self.assertEqual(1, rp.adjustment)
        self.assertEqual(2, rp.total)
        self.assertIn(
            "Needed to adjust inventories", self.stdlog.logger.output)

    def test_adjust_for_removals_allocated_removed_no_inventory(self):
        rp = ppt.PciResourceProvider("fake-node_0000:72:00.0")

        pt = provider_tree.ProviderTree()
        pt.new_root("fake-node", uuids.compute_rp)
        pt.new_child("fake-node_0000:72:00.0", uuids.compute_rp, uuids.pci)

        # One allocation exists but no inventory at all. The RC will be
        # inferred from the allocation and the inventory is adjusted
        usage = {uuids.pci: {"CUSTOM_PCI_DEAD_BEEF": 1}}

        rp._adjust_for_removals_and_held_devices(pt, usage)

        self.assertEqual(0, len(rp.devs))
        self.assertEqual(1, rp.adjustment)
        self.assertEqual(1, rp.total)
        self.assertIn(
            "Needed to adjust inventories", self.stdlog.logger.output)
