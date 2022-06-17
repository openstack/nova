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
import ddt
from unittest import mock

from nova.compute import pci_placement_translator as ppt
from nova.objects import pci_device
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
            objects=[pci_device.PciDevice(address="0000:81:00.0")]
        )
        # So we have a device but there is no spec for it
        pci_tracker.dev_filter.get_devspec = mock.Mock(return_value=None)
        # we expect that the provider_tree is not touched as the device without
        # spec is skipped, we assert that with the NonCallableMock
        provider_tree = mock.NonCallableMock()

        ppt.update_provider_tree_for_pci(
            provider_tree, "fake-node", pci_tracker, {})

        self.assertIn(
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
            expected_traits, ppt._get_traits_for_dev({"traits": trait_names}))

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
            ppt._get_rc_for_dev(pci_dev, {"resource_class": rc_name})
        )
