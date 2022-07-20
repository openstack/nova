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
from unittest import mock

import fixtures
import os_resource_classes
import os_traits
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import exception
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_sriov_servers

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PlacementPCIReportingTests(test_pci_sriov_servers._PCIServersTestBase):
    PCI_RC = f"CUSTOM_PCI_{fakelibvirt.PCI_VEND_ID}_{fakelibvirt.PCI_PROD_ID}"
    PF_RC = f"CUSTOM_PCI_{fakelibvirt.PCI_VEND_ID}_{fakelibvirt.PF_PROD_ID}"
    VF_RC = f"CUSTOM_PCI_{fakelibvirt.PCI_VEND_ID}_{fakelibvirt.VF_PROD_ID}"

    # Just placeholders to satisfy the base class. The real value will be
    # redefined by the tests
    PCI_DEVICE_SPEC = []
    PCI_ALIAS = None

    def setUp(self):
        super().setUp()
        patcher = mock.patch(
            "nova.compute.pci_placement_translator."
            "_is_placement_tracking_enabled",
            return_value=True
        )
        self.addCleanup(patcher.stop)
        self.mock_pci_report_in_placement = patcher.start()

        # These tests should not depend on the host's sysfs
        self.useFixture(
            fixtures.MockPatch('nova.pci.utils.is_physical_function'))
        self.useFixture(
            fixtures.MockPatch(
                'nova.pci.utils.get_function_by_ifname',
                return_value=(None, False)
            )
        )

    @staticmethod
    def _to_device_spec_conf(spec_list):
        return [jsonutils.dumps(x) for x in spec_list]

    def test_new_compute_init_with_pci_devs(self):
        """A brand new compute is started with multiple pci devices configured
        for nova.
        """
        # The fake libvirt will emulate on the host:
        # * two type-PCI devs (slot 0 and 1)
        # * two type-PFs (slot 2 and 3) with two type-VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=2, num_vfs=4)

        # the emulated devices will then be filtered by the device_spec:
        device_spec = self._to_device_spec_conf(
            [
                # PCI_PROD_ID will match two type-PCI devs (slot 0, 1)
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                    "traits": ",".join(
                        [os_traits.HW_GPU_API_VULKAN, "CUSTOM_GPU", "purple"]
                    )
                },
                # PF_PROD_ID + slot 2 will match one PF but not their children
                # VFs
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:02.0",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV, "CUSTOM_PF", "pf-white"]
                    ),
                },
                # VF_PROD_ID + slot 3 will match two VFs but not their parent
                # PF
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:03.*",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV_TRUSTED, "CUSTOM_VF", "vf-red"]
                    ),
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        # Finally we assert that only the filtered devices are reported to
        # placement.
        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
                # Note that the VF inventory is reported on the parent PF
                "0000:81:03.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [
                    "HW_GPU_API_VULKAN",
                    "CUSTOM_GPU",
                    "CUSTOM_PURPLE",
                ],
                "0000:81:01.0": [
                    "HW_GPU_API_VULKAN",
                    "CUSTOM_GPU",
                    "CUSTOM_PURPLE",
                ],
                "0000:81:02.0": [
                    "HW_NIC_SRIOV",
                    "CUSTOM_PF",
                    "CUSTOM_PF_WHITE",
                ],
                "0000:81:03.0": [
                    "HW_NIC_SRIOV_TRUSTED",
                    "CUSTOM_VF",
                    "CUSTOM_VF_RED",
                ],
            },
        )

    def test_new_compute_init_with_pci_dev_custom_rc(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI devs slot 0
        # * one type-PF dev in slot 1 with a single type-VF under it
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=1, num_vfs=1)

        device_spec = self._to_device_spec_conf(
            [
                # PCI_PROD_ID will match the type-PCI in slot 0
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                    "resource_class": os_resource_classes.PGPU,
                    "traits": os_traits.HW_GPU_API_VULKAN,
                },
                # slot 1 func 0 is the type-PF dev. The child VF is ignored
                {
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:01.0",
                    "resource_class": "crypto",
                    "traits": "to-the-moon,hodl"
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {os_resource_classes.PGPU: 1},
                "0000:81:01.0": {"CUSTOM_CRYPTO": 1},
            },
            traits={
                "0000:81:00.0": [
                    "HW_GPU_API_VULKAN",
                ],
                "0000:81:01.0": [
                    "CUSTOM_TO_THE_MOON",
                    "CUSTOM_HODL",
                ],
            },
        )

    def test_dependent_device_config_is_rejected(self):
        """Configuring both the PF and its children VFs is not supported.
        Only either of them can be given to nova.
        """
        # The fake libvirt will emulate on the host:
        # * one type-PF dev in slot 0 with a single type-VF under it
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        # both device will be matched by our config
        device_spec = self._to_device_spec_conf(
            [
                # PF
                {
                    "address": "0000:81:00.0"
                },
                # Its child VF
                {
                    "address": "0000:81:00.1"
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        ex = self.assertRaises(
            exception.PlacementPciException,
            self.start_compute,
            hostname="compute1",
            pci_info=pci_info
        )
        self.assertIn(
            "Configuring both 0000:81:00.1 and 0000:81:00.0 in "
            "[pci]device_spec is not supported",
            str(ex)
        )

    def test_sibling_vfs_with_contradicting_resource_classes_rejected(self):
        # The fake libvirt will emulate on the host:
        # * one type-PF dev in slot 0 with two type-VF under it
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # the config matches the two VFs separately and tries to configure
        # them with different resource class
        device_spec = self._to_device_spec_conf(
            [
                {
                    "address": "0000:81:00.1",
                    "resource_class": "vf1"
                },
                {
                    "address": "0000:81:00.2",
                    "resource_class": "vf2"
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        ex = self.assertRaises(
            exception.PlacementPciMixedResourceClassException,
            self.start_compute,
            hostname="compute1",
            pci_info=pci_info
        )
        self.assertIn(
            "VFs from the same PF cannot be configured with different "
            "'resource_class' values in [pci]device_spec. We got "
            "CUSTOM_VF2 for 0000:81:00.2 and CUSTOM_VF1 for 0000:81:00.1.",
            str(ex)
        )

    def test_sibling_vfs_with_contradicting_traits_rejected(self):
        # The fake libvirt will emulate on the host:
        # * one type-PF dev in slot 0 with two type-VF under it
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # the config matches the two VFs separately and tries to configure
        # them with different trait list
        device_spec = self._to_device_spec_conf(
            [
                {
                    "address": "0000:81:00.1",
                    "traits": "foo",
                },
                {
                    "address": "0000:81:00.2",
                    "traits": "bar",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        ex = self.assertRaises(
            exception.PlacementPciMixedTraitsException,
            self.start_compute,
            hostname="compute1",
            pci_info=pci_info
        )
        self.assertIn(
            "VFs from the same PF cannot be configured with different set of "
            "'traits' in [pci]device_spec. We got "
            "COMPUTE_MANAGED_PCI_DEVICE,CUSTOM_BAR for 0000:81:00.2 and "
            "COMPUTE_MANAGED_PCI_DEVICE,CUSTOM_FOO for 0000:81:00.1.",
            str(ex)
        )

    def test_neutron_sriov_devs_ignored(self):
        # The fake libvirt will emulate on the host:
        # * one type-PF dev in slot 0 with one type-VF under it
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        # then the config assigns physnet to the dev
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "physical_network": "physnet0",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        # As every matching dev has physnet configured they are ignored
        self.assert_placement_pci_view(
            "compute1",
            inventories={},
            traits={},
        )

    def test_devname_based_dev_spec_rejected(self):
        device_spec = self._to_device_spec_conf(
            [
                {
                    "devname": "eth0",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        ex = self.assertRaises(
            exception.PlacementPciException,
            self.start_compute,
            hostname="compute1",
        )
        self.assertIn(
            " Invalid [pci]device_spec configuration. PCI Placement reporting "
            "does not support 'devname' based device specification but we got "
            "{'devname': 'eth0'}. Please use PCI address in the configuration "
            "instead.",
            str(ex)
        )

    def test_remove_pci(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        # the config matches that PCI dev
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PCI_RC: 1},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # now un-configure the PCI device and restart the compute
        self.flags(group='pci', device_spec=self._to_device_spec_conf([]))
        self.restart_compute_service(hostname="compute1")

        # the RP had no allocation so nova could remove it
        self.assert_placement_pci_view(
            "compute1",
            inventories={},
            traits={},
        )

    def test_remove_one_vf(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs in slot 0 with two type-VFs 00.1, 00.2
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # then the config matching the VFs
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # remove one of the VFs from the hypervisor and then restart the
        # compute
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )

        # total value is expected to decrease to 1
        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.VF_RC: 1},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

    def test_remove_all_vfs(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs in slot 0 with two type-VFs 00.1, 00.2
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # then the config patches the VFs
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # remove both VFs from the hypervisor and restart the compute
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=0)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )

        # we expect that the RP is deleted
        self.assert_placement_pci_view(
            "compute1",
            inventories={},
            traits={},
        )

    def test_remove_all_vfs_add_pf(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs in slot 0 with two type-VFs 00.1, 00.2
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # then the config matches both VFs
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # change the config to match the PF but do not match the VFs and
        # restart the compute
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )

        # we expect that VF inventory is removed and the PF inventory is added
        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PF_RC: 1},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

    def test_remove_pf_add_vfs(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs in slot 0 with two type-VFs 00.1, 00.2
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # then the config only matches the PF
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PF_RC: 1},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # remove the PF from the config and add the VFs instead then restart
        # the compute
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )

        # we expect that PF inventory is removed and the VF inventory is added
        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

    def test_device_reconfiguration(self):
        # The fake libvirt will emulate on the host:
        # * two type-PFs in slot 0, 1 with two type-VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=2, num_vfs=4)
        # from slot 0 we match the PF only and ignore the VFs
        # from slot 1 we match the VFs but ignore the parent PF
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:00.0",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV, "CUSTOM_PF", "pf-white"]
                    ),
                },
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:01.*",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV_TRUSTED, "CUSTOM_VF", "vf-red"]
                    ),
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PF_RC: 1},
                "0000:81:01.0": {self.VF_RC: 2},
            },
            traits={
                "0000:81:00.0": [
                    "HW_NIC_SRIOV",
                    "CUSTOM_PF",
                    "CUSTOM_PF_WHITE",
                ],
                "0000:81:01.0": [
                    "HW_NIC_SRIOV_TRUSTED",
                    "CUSTOM_VF",
                    "CUSTOM_VF_RED",
                ],
            },
        )

        # change the resource class and traits configuration and restart the
        # compute
        device_spec = self._to_device_spec_conf(
            [
                {
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "resource_class": "CUSTOM_PF",
                    "address": "0000:81:00.0",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV, "pf-black"]
                    ),
                },
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "resource_class": "CUSTOM_VF",
                    "address": "0000:81:01.*",
                    "traits": ",".join(
                        [os_traits.HW_NIC_SRIOV_TRUSTED, "vf-blue", "foobar"]
                    ),
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {"CUSTOM_PF": 1},
                "0000:81:01.0": {"CUSTOM_VF": 2},
            },
            traits={
                "0000:81:00.0": [
                    "HW_NIC_SRIOV",
                    "CUSTOM_PF_BLACK",
                ],
                "0000:81:01.0": [
                    "HW_NIC_SRIOV_TRUSTED",
                    "CUSTOM_VF_BLUE",
                    "CUSTOM_FOOBAR",
                ],
            },
        )

    def test_reporting_disabled_nothing_is_reported(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        # the config matches the PCI dev
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        # Disable placement reporting so even if there are PCI devices on the
        # hypervisor matching the [pci]device_spec config they are not reported
        # to Placement
        self.mock_pci_report_in_placement.return_value = False
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={},
            traits={},
        )

    def test_reporting_cannot_be_disable_once_it_is_enabled(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        # the config matches the PCI dev
        device_spec = self._to_device_spec_conf(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {self.PCI_RC: 1},
            },
            traits={
                "0000:81:00.0": [],
            },
        )

        # Try to disable placement reporting. The compute will refuse to start
        # as there are already PCI device RPs in placement.
        self.mock_pci_report_in_placement.return_value = False
        ex = self.assertRaises(
            exception.PlacementPciException,
            self.restart_compute_service,
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False,
        )
        self.assertIn(
            "The [pci]report_in_placement is False but it was enabled before "
            "on this compute. Nova does not support disabling it after it is "
            "enabled.",
            str(ex)
        )
