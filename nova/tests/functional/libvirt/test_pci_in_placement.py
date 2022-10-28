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

import ddt
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
    PCI_ALIAS = [
        jsonutils.dumps(x)
        for x in (
            {
                "vendor_id": fakelibvirt.PCI_VEND_ID,
                "product_id": fakelibvirt.PCI_PROD_ID,
                "name": "a-pci-dev",
            },
            {
                "vendor_id": fakelibvirt.PCI_VEND_ID,
                "product_id": fakelibvirt.PF_PROD_ID,
                "device_type": "type-PF",
                "name": "a-pf",
            },
            {
                "vendor_id": fakelibvirt.PCI_VEND_ID,
                "product_id": fakelibvirt.VF_PROD_ID,
                "device_type": "type-VF",
                "name": "a-vf",
            },
        )
    ]

    def setUp(self):
        super().setUp()
        self.flags(group="pci", report_in_placement=True)

        # These tests should not depend on the host's sysfs
        self.useFixture(
            fixtures.MockPatch('nova.pci.utils.is_physical_function'))
        self.useFixture(
            fixtures.MockPatch(
                'nova.pci.utils.get_function_by_ifname',
                return_value=(None, False)
            )
        )


class PlacementPCIInventoryReportingTests(PlacementPCIReportingTests):

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
        device_spec = self._to_list_of_json_str(
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

        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        self.flags(group='pci', device_spec=self._to_list_of_json_str([]))
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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
        device_spec = self._to_list_of_json_str(
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

    def _create_one_compute_with_a_pf_consumed_by_an_instance(self):
        # The fake libvirt will emulate on the host:
        # * two type-PFs in slot 0, with one type-VF
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        # we match the PF only and ignore the VF
        device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:00.0",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assertPCIDeviceCounts("compute1", total=1, free=1)
        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.PF_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # Create an instance consuming the PF
        extra_spec = {"pci_passthrough:alias": "a-pf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts("compute1", total=1, free=0)
        compute1_expected_placement_view["usages"] = {
            "0000:81:00.0": {self.PF_RC: 1},
        }
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.PF_RC: 1},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        return server, compute1_expected_placement_view

    def test_device_reconfiguration_with_allocations_config_change_warn(self):
        server, compute1_expected_placement_view = (
            self._create_one_compute_with_a_pf_consumed_by_an_instance())

        # remove 0000:81:00.0 from the device spec and restart the compute
        device_spec = self._to_list_of_json_str([])
        self.flags(group='pci', device_spec=device_spec)
        # The PF is used but removed from the config. The PciTracker warns
        # but keeps the device so the placement logic mimic this and only warns
        # but keeps the RP and the allocation in placement intact.
        self.restart_compute_service(hostname="compute1")
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        # the warning from the PciTracker
        self.assertIn(
            "WARNING [nova.pci.manager] Unable to remove device with status "
            "'allocated' and ownership %s because of PCI device "
            "1:0000:81:00.0 is allocated instead of ['available', "
            "'unavailable', 'unclaimable']. Check your [pci]device_spec "
            "configuration to make sure this allocated device is whitelisted. "
            "If you have removed the device from the whitelist intentionally "
            "or the device is no longer available on the host you will need "
            "to delete the server or migrate it to another host to silence "
            "this warning."
            % server['id'],
            self.stdlog.logger.output,
        )
        # the warning from the placement PCI tracking logic
        self.assertIn(
            "WARNING [nova.compute.pci_placement_translator] Device spec is "
            "not found for device 0000:81:00.0 in [pci]device_spec. We are "
            "skipping this devices during Placement update. The device is "
            "allocated by %s. You should not remove an allocated device from "
            "the configuration. Please restore the configuration or cold "
            "migrate the instance to resolve the inconsistency."
            % server['id'],
            self.stdlog.logger.output,
        )

    def test_device_reconfiguration_with_allocations_config_change_stop(self):
        self._create_one_compute_with_a_pf_consumed_by_an_instance()

        # switch 0000:81:00.0 PF to 0000:81:00.1 VF
        # in the config, then restart the compute service

        # only match the VF now
        device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:00.1",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        # The compute fails to start as the new config would mean that the PF
        # inventory is removed from the 0000:81:00.0 RP and the PF inventory is
        # added instead there, but the VF inventory has allocations. Keeping
        # the old inventory as in
        # test_device_reconfiguration_with_allocations_config_change_warn is
        # not an option as it would result in two resource class on the same RP
        # one for the PF and one for the VF. That would allow consuming
        # the same physical device twice. Such dependent device configuration
        # is intentionally not supported so we are stopping the compute
        # service.
        ex = self.assertRaises(
            exception.PlacementPciException,
            self.restart_compute_service,
            hostname="compute1"
        )
        self.assertRegex(
            str(ex),
            "Failed to gather or report PCI resources to Placement: There was "
            "a conflict when trying to complete your request.\n\n "
            "update conflict: Inventory for 'CUSTOM_PCI_8086_1528' on "
            "resource provider '.*' in use.",
        )

    def test_device_reconfiguration_with_allocations_hyp_change(self):
        server, compute1_expected_placement_view = (
            self._create_one_compute_with_a_pf_consumed_by_an_instance())

        # restart the compute but simulate that the device 0000:81:00.0 is
        # removed from the hypervisor while the device spec config left
        # intact. The PciTracker will notice this and log a warning. The
        # placement tracking logic simply keeps the allocation intact in
        # placement as both the PciDevice and the DeviceSpec is available.
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0)
        self.restart_compute_service(
            hostname="compute1",
            pci_info=pci_info,
            keep_hypervisor_state=False
        )
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        # the warning from the PciTracker
        self.assertIn(
            "WARNING [nova.pci.manager] Unable to remove device with status "
            "'allocated' and ownership %s because of PCI device "
            "1:0000:81:00.0 is allocated instead of ['available', "
            "'unavailable', 'unclaimable']. Check your [pci]device_spec "
            "configuration to make sure this allocated device is whitelisted. "
            "If you have removed the device from the whitelist intentionally "
            "or the device is no longer available on the host you will need "
            "to delete the server or migrate it to another host to silence "
            "this warning."
            % server['id'],
            self.stdlog.logger.output,
        )

    def test_reporting_disabled_nothing_is_reported(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        # the config matches the PCI dev
        device_spec = self._to_list_of_json_str(
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
        self.flags(group="pci", report_in_placement=False)
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
        device_spec = self._to_list_of_json_str(
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
        self.flags(group="pci", report_in_placement=False)
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


class PlacementPCIAllocationHealingTests(PlacementPCIReportingTests):
    def setUp(self):
        super().setUp()
        # Make migration succeed
        self.useFixture(
            fixtures.MockPatch(
                "nova.virt.libvirt.driver.LibvirtDriver."
                "migrate_disk_and_power_off",
                new=mock.Mock(return_value='{}'),
            )
        )

    def test_heal_single_pci_allocation(self):
        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        # the config matches the PCI dev
        device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        # Start a compute *without* PCI tracking in placement
        self.flags(group="pci", report_in_placement=False)
        self.start_compute(hostname="compute1", pci_info=pci_info)
        self.assertPCIDeviceCounts("compute1", total=1, free=1)

        # Create an instance that consume our PCI dev
        extra_spec = {"pci_passthrough:alias": "a-pci-dev:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=1, free=0)

        # Restart the compute but now with PCI tracking enabled
        self.flags(group="pci", report_in_placement=True)
        self.restart_compute_service("compute1")
        # Assert that the PCI allocation is healed in placement
        self.assertPCIDeviceCounts("compute1", total=1, free=0)
        expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 1}
            },
            "allocations": {
                server['id']: {
                    "0000:81:00.0": {self.PCI_RC: 1}
                }
            }
        }
        self.assert_placement_pci_view("compute1", **expected_placement_view)

        # run an update_available_resources periodic and assert that the usage
        # and allocation stays
        self._run_periodics()
        self.assert_placement_pci_view("compute1", **expected_placement_view)

    def test_heal_multiple_allocations(self):
        # The fake libvirt will emulate on the host:
        # * two type-PCI devs (slot 0 and 1)
        # * two type-PFs (slot 2 and 3) with 4 type-VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=2, num_vfs=8)
        # the config matches:
        device_spec = self._to_list_of_json_str(
            [
                # both type-PCI
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
                # the PF in slot 2
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:02.0",
                },
                # the VFs in slot 3
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:03.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        # Start a compute *without* PCI tracking in placement
        self.flags(group="pci", report_in_placement=False)
        self.start_compute(hostname="compute1", pci_info=pci_info)
        # 2 PCI + 1 PF + 4 VFs
        self.assertPCIDeviceCounts("compute1", total=7, free=7)

        # Create three instances consuming devices:
        # * server_2pci: two type-PCI
        # * server_pf_vf: one PF and one VF
        # * server_2vf: two VFs
        extra_spec = {"pci_passthrough:alias": "a-pci-dev:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_2pci = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=7, free=5)

        extra_spec = {"pci_passthrough:alias": "a-pf:1,a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_pf_vf = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=7, free=3)

        extra_spec = {"pci_passthrough:alias": "a-vf:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_2vf = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=7, free=1)

        # Restart the compute but now with PCI tracking enabled
        self.flags(group="pci", report_in_placement=True)
        self.restart_compute_service("compute1")
        # Assert that the PCI allocation is healed in placement
        self.assertPCIDeviceCounts("compute1", total=7, free=1)
        expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
                "0000:81:03.0": {self.VF_RC: 4},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
                "0000:81:03.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
                "0000:81:03.0": {self.VF_RC: 3},
            },
            "allocations": {
                server_2pci['id']: {
                    "0000:81:00.0": {self.PCI_RC: 1},
                    "0000:81:01.0": {self.PCI_RC: 1},
                },
                server_pf_vf['id']: {
                    "0000:81:02.0": {self.PF_RC: 1},
                    "0000:81:03.0": {self.VF_RC: 1},
                },
                server_2vf['id']: {
                    "0000:81:03.0": {self.VF_RC: 2}
                },
            },
        }
        self.assert_placement_pci_view("compute1", **expected_placement_view)

        # run an update_available_resources periodic and assert that the usage
        # and allocation stays
        self._run_periodics()
        self.assert_placement_pci_view("compute1", **expected_placement_view)

    def test_heal_partial_allocations(self):
        # The fake libvirt will emulate on the host:
        # * two type-PCI devs (slot 0 and 1)
        # * two type-PFs (slot 2 and 3) with 4 type-VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=2, num_vfs=8)
        # the config matches:
        device_spec = self._to_list_of_json_str(
            [
                # both type-PCI
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
                # the PF in slot 2
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:02.0",
                },
                # the VFs in slot 3
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:03.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)

        # Start a compute with PCI tracking in placement
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute1", pci_info=pci_info)
        # 2 PCI + 1 PF + 4 VFs
        self.assertPCIDeviceCounts("compute1", total=7, free=7)
        expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
                "0000:81:03.0": {self.VF_RC: 4},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
                "0000:81:03.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
                "0000:81:02.0": {self.PF_RC: 0},
                "0000:81:03.0": {self.VF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view("compute1", **expected_placement_view)

        # Create an instance consuming a VF
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_vf = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=7, free=6)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler. BUT the resource
        # tracker in the compute will heal the missing PCI allocation
        expected_placement_view["usages"]["0000:81:03.0"][self.VF_RC] = 1
        expected_placement_view["allocations"][server_vf["id"]] = {
            "0000:81:03.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view("compute1", **expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view("compute1", **expected_placement_view)

        # Create another instance consuming two VFs
        extra_spec = {"pci_passthrough:alias": "a-vf:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_2vf = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=7, free=4)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler. BUT the resource
        # tracker in the compute will heal the missing PCI allocation
        expected_placement_view["usages"]["0000:81:03.0"][self.VF_RC] = 3
        expected_placement_view["allocations"][server_2vf["id"]] = {
            "0000:81:03.0": {self.VF_RC: 2}
        }
        self.assert_placement_pci_view("compute1", **expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view("compute1", **expected_placement_view)

    def test_heal_partial_allocations_during_resize_downsize(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs (slot 0) with 2 type-VFs
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=2)
        # the config matches just the VFs
        compute1_device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:00.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=compute1_device_spec)

        # Start a compute with PCI tracking in placement
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute1", pci_info=compute1_pci_info)
        self.assertPCIDeviceCounts("compute1", total=2, free=2)
        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.VF_RC: 2},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.VF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # Create an instance consuming two VFs
        extra_spec = {"pci_passthrough:alias": "a-vf:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=2, free=0)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler. BUT the resource
        # tracker in the compute will heal the missing PCI allocation
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 2
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 2}
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # Resize server to use only one VF

        # Start a new compute with only one VF available
        # The fake libvirt will emulate on the host:
        # * one type-PFs (slot 0) with 1 type-VFs
        compute2_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        # the config matches just the VFs
        compute2_device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:00.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=compute2_device_spec)

        # Start a compute with PCI tracking in placement
        self.start_compute(hostname="compute2", pci_info=compute2_pci_info)
        self.assertPCIDeviceCounts("compute2", total=1, free=1)
        compute2_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.VF_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.VF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)

        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._resize_server(server, flavor_id)

        self.assertPCIDeviceCounts("compute2", total=1, free=0)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler on the
        # destination. BUT the resource tracker in the compute will heal the
        # missing PCI allocation
        compute2_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 1
        compute2_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        # the resize is not confirmed, so we expect that the source host
        # still has PCI allocation in placement, but it is held by the
        # migration UUID now.
        self._move_server_allocation(
            compute1_expected_placement_view["allocations"], server['id'])
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # revert the resize
        server = self._revert_resize(server)
        # the dest host should be freed up
        compute2_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 0
        del compute2_expected_placement_view["allocations"][server["id"]]
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        # on the source host the allocation should be moved back from the
        # migration UUID to the instance UUID
        self._move_server_allocation(
            compute1_expected_placement_view["allocations"],
            server['id'],
            revert=True
        )
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # resize again and this time confirm the resize
        server = self._resize_server(server, flavor_id)
        server = self._confirm_resize(server)
        # the dest should have the allocation for the server
        compute2_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 1
        compute2_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        # the source host should be freed
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 0
        del compute1_expected_placement_view["allocations"][server["id"]]
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

    def test_heal_partial_allocations_during_resize_change_dev_type(self):
        # The fake libvirt will emulate on the host:
        # * one type-PFs (slot 0) with 1 type-VFs
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=1)
        # the config matches just the VFs
        compute1_device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:00.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=compute1_device_spec)

        # Start a compute with PCI tracking in placement
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute1", pci_info=compute1_pci_info)
        self.assertPCIDeviceCounts("compute1", total=1, free=1)
        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.VF_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.VF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # Create an instance consuming one VFs
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=1, free=0)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler. BUT the resource
        # tracker in the compute will heal the missing PCI allocation
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 1
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # Resize the instance to consume a PF and two PCI devs instead

        # start a compute with enough devices for the resize
        # The fake libvirt will emulate on the host:
        # * two type-PCI (slot 0, 1)
        # * one type-PFs (slot 2) with 1 type-VFs
        compute2_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=1, num_vfs=1)
        # the config matches the PCI devs and hte PF but not the VFs
        compute2_device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                    "address": "0000:81:*",
                },
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:*",
                },
            ]
        )
        self.flags(group='pci', device_spec=compute2_device_spec)

        # Start a compute with PCI tracking in placement
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute2", pci_info=compute2_pci_info)
        self.assertPCIDeviceCounts("compute2", total=3, free=3)
        compute2_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
                "0000:81:02.0": {self.PF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)

        # resize the server to consume a PF and two PCI devs instead
        extra_spec = {"pci_passthrough:alias": "a-pci-dev:2,a-pf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._resize_server(server, flavor_id)
        server = self._confirm_resize(server)

        # on the dest we have the new PCI allocations
        self.assertPCIDeviceCounts("compute2", total=3, free=0)
        compute2_expected_placement_view["usages"] = (
            {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PF_RC: 1},
            }
        )
        compute2_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.PCI_RC: 1},
            "0000:81:01.0": {self.PCI_RC: 1},
            "0000:81:02.0": {self.PF_RC: 1},
        }
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute2", **compute2_expected_placement_view)

        # on the source the allocation is freed up
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 0
        del compute1_expected_placement_view["allocations"][server["id"]]
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

    def test_heal_allocation_during_same_host_resize(self):
        self.flags(allow_resize_to_same_host=True)
        # The fake libvirt will emulate on the host:
        # * one type-PFs (slot 0) with 3 type-VFs
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=1, num_vfs=3)
        # the config matches just the VFs
        compute1_device_spec = self._to_list_of_json_str(
            [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:00.*",
                },
            ]
        )
        self.flags(group='pci', device_spec=compute1_device_spec)
        # Start a compute with PCI tracking in placement
        self.flags(group="pci", report_in_placement=True)
        self.start_compute(hostname="compute1", pci_info=compute1_pci_info)
        self.assertPCIDeviceCounts("compute1", total=3, free=3)
        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {self.VF_RC: 3},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.VF_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        # Create an instance consuming one VFs
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=3, free=2)
        # As scheduling does not support PCI in placement yet no allocation
        # is created for the PCI consumption by the scheduler. BUT the resource
        # tracker in the compute will heal the missing PCI allocation
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 1
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # resize the server to consume 2 VFs on the same host
        extra_spec = {"pci_passthrough:alias": "a-vf:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._resize_server(server, flavor_id)
        # during resize both the source and the dest allocation is kept
        # and in same host resize that means both consumed from the same host
        self.assertPCIDeviceCounts("compute1", total=3, free=0)
        # the source side of the allocation held by the migration
        self._move_server_allocation(
            compute1_expected_placement_view["allocations"], server['id'])
        # NOTE(gibi): we intentionally don't heal allocation for the instance
        # while it is being resized. See the comment in the
        # pci_placement_translator about the reasoning.
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # revert the resize
        self._revert_resize(server)
        self.assertPCIDeviceCounts("compute1", total=3, free=2)
        # the original allocations are restored
        self._move_server_allocation(
            compute1_expected_placement_view["allocations"],
            server["id"],
            revert=True,
        )
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 1
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 1}
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # now resize and then confirm it
        self._resize_server(server, flavor_id)
        self._confirm_resize(server)

        # we expect that the consumption is according to the new flavor
        self.assertPCIDeviceCounts("compute1", total=3, free=1)
        compute1_expected_placement_view[
            "usages"]["0000:81:00.0"][self.VF_RC] = 2
        compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {self.VF_RC: 2}
        }
        # NOTE(gibi): This is unfortunate but during same host resize
        # confirm when the PCI scheduling is not enabled the healing logic
        # cannot heal the dest host allocation during the claim. It will only
        # heal it in the next run of the  ResourceTracker._update(). This due
        # to the fact that ResourceTracker.drop_move_claim runs both for
        # revert (on the dest) and confirm (on the source) and in same host
        # resize this means that it runs on both the source and the dest as
        # they are the same.
        # Anyhow the healing will happen just a bit later. And the end goal is
        # to make the scheduler support enabled by default and delete the
        # whole healing logic. So I think this is acceptable.
        self._run_periodics()
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)


@ddt.ddt
class SimpleRCAndTraitBasedPCIAliasTests(PlacementPCIReportingTests):
    def setUp(self):
        super().setUp()
        self.flags(group='filter_scheduler', pci_in_placement=True)

        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=0, num_vfs=0)
        device_spec = self._to_list_of_json_str(
            [
                {
                    "address": "0000:81:00.0",
                    "resource_class": "gpu",
                    "traits": ",".join(
                        [
                            os_traits.HW_GPU_API_VULKAN,
                            "purple",
                            "round",
                        ]
                    ),
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assertPCIDeviceCounts("compute1", total=1, free=1)
        self.compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {"CUSTOM_GPU": 1},
            },
            "traits": {
                "0000:81:00.0": [
                    "HW_GPU_API_VULKAN",
                    "CUSTOM_PURPLE",
                    "CUSTOM_ROUND",
                ],
            },
            "usages": {
                "0000:81:00.0": {"CUSTOM_GPU": 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **self.compute1_expected_placement_view)

    @ddt.data(
        {
            "vendor_id": fakelibvirt.PCI_VEND_ID,
            "product_id": fakelibvirt.PCI_PROD_ID,
            "name": "a-gpu-wrong-rc",
        },
        {
            "resource_class": os_resource_classes.PGPU,
            "name": "a-gpu-wrong-rc-2",
        },
        {
            "resource_class": "GPU",
            # NOTE(gibi): "big" is missing from device spec
            "traits": "purple,big",
            "name": "a-gpu-missing-trait",
        },
    )
    def test_boot_with_custom_rc_and_traits_no_matching_device(
        self, pci_alias
    ):
        self.flags(group="pci", alias=self._to_list_of_json_str([pci_alias]))
        extra_spec = {"pci_passthrough:alias": f"{pci_alias['name']}:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks=[], expected_state="ERROR"
        )
        self.assertIn("fault", server)
        self.assertIn("No valid host", server["fault"]["message"])

        self.assertPCIDeviceCounts("compute1", total=1, free=1)
        self.assert_placement_pci_view(
            "compute1", **self.compute1_expected_placement_view
        )

    def test_boot_with_custom_rc_and_traits_succeeds(self):
        pci_alias_gpu = {
            "resource_class": "GPU",
            "traits": "HW_GPU_API_VULKAN,PURPLE",
            "name": "a-gpu",
        }
        self.flags(
            group="pci", alias=self._to_list_of_json_str([pci_alias_gpu])
        )

        extra_spec = {"pci_passthrough:alias": "a-gpu:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts("compute1", total=1, free=0)
        self.compute1_expected_placement_view["usages"]["0000:81:00.0"][
            "CUSTOM_GPU"
        ] = 1
        self.compute1_expected_placement_view["allocations"][server["id"]] = {
            "0000:81:00.0": {"CUSTOM_GPU": 1}
        }
        self.assert_placement_pci_view(
            "compute1", **self.compute1_expected_placement_view
        )
        self.assert_no_pci_healing("compute1")


class RCAndTraitBasedPCIAliasTests(PlacementPCIReportingTests):
    def setUp(self):
        super().setUp()
        self.flags(group='filter_scheduler', pci_in_placement=True)

    def test_device_claim_consistent_with_placement_allocation(self):
        """As soon as [filter_scheduler]pci_in_placement is enabled the
        nova-scheduler will allocate PCI devices in placement. Then on the
        nova-compute side the PCI claim will also allocate PCI devices in the
        nova DB. This test will create a situation where the two allocation
        could contradict and observes that in a contradicting situation the PCI
        claim will fail instead of allocating a device that is not allocated in
        placement.

        For the contradiction to happen we need two PCI devices that looks
        different from placement perspective than from the nova DB perspective.

        We can do that by assigning different traits from in placement and
        having different product_id in the Nova DB. Then we will create a
        request that would match from placement perspective to one of the
        device only and would match to the other device from nova DB
        perspective. Then we will expect that the boot request fails with no
        valid host.
        """
        # The fake libvirt will emulate on the host:
        # * one type-PCI in slot 0
        # * one type-PF in slot 1
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, num_pfs=1, num_vfs=0)
        # we allow both device to be consumed, but we assign different traits
        # so we can selectively schedule to one of the devices in placement
        device_spec = self._to_list_of_json_str(
            [
                {
                    "address": "0000:81:00.0",
                    "resource_class": "MY_DEV",
                    "traits": "A_PCI",
                },
                {
                    "address": "0000:81:01.0",
                    "resource_class": "MY_DEV",
                    "traits": "A_PF",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        self.assertPCIDeviceCounts("compute1", total=2, free=2)
        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {"CUSTOM_MY_DEV": 1},
                "0000:81:01.0": {"CUSTOM_MY_DEV": 1},
            },
            "traits": {
                "0000:81:00.0": [
                    "CUSTOM_A_PCI",
                ],
                "0000:81:01.0": [
                    "CUSTOM_A_PF",
                ],
            },
            "usages": {
                "0000:81:00.0": {"CUSTOM_MY_DEV": 0},
                "0000:81:01.0": {"CUSTOM_MY_DEV": 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)

        # now we create a PCI alias that cannot be fulfilled from both
        # nova and placement perspective at the same time, but can be fulfilled
        # from each perspective individually
        pci_alias_no_match = {
            "resource_class": "MY_DEV",
            # by product_id this matches 81.00 only
            "product_id": fakelibvirt.PCI_PROD_ID,
            # by trait this matches 81.01 only
            "traits": "A_PF",
            "name": "a-pci",
        }
        self.flags(
            group="pci",
            alias=self._to_list_of_json_str([pci_alias_no_match]),
        )

        # then try to boot with the alias and expect no valid host error
        extra_spec = {"pci_passthrough:alias": "a-pci:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks=[], expected_state='ERROR')
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assert_no_pci_healing("compute1")

    def test_vf_with_split_allocation(self):
        # The fake libvirt will emulate on the host:
        # * two type-PFs in slot 0, 1 with 2 VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=2, num_vfs=4)
        # make all 4 VFs available
        device_spec = self._to_list_of_json_str(
            [
                {
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "resource_class": "MY_VF",
                    "traits": "blue",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {"CUSTOM_MY_VF": 2},
                "0000:81:01.0": {"CUSTOM_MY_VF": 2},
            },
            "traits": {
                "0000:81:00.0": [
                    "CUSTOM_BLUE",
                ],
                "0000:81:01.0": [
                    "CUSTOM_BLUE",
                ],
            },
            "usages": {
                "0000:81:00.0": {"CUSTOM_MY_VF": 0},
                "0000:81:01.0": {"CUSTOM_MY_VF": 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assertPCIDeviceCounts('compute1', total=4, free=4)

        pci_alias_vf = {
            "resource_class": "MY_VF",
            "traits": "blue",
            "name": "a-vf",
        }
        self.flags(
            group="pci",
            alias=self._to_list_of_json_str([pci_alias_vf]),
        )

        # reserve VFs from 81.01 in placement to drive the first instance to
        # 81.00
        self._reserve_placement_resource(
            "compute1_0000:81:01.0", "CUSTOM_MY_VF", 2)
        # boot an instance with a single VF
        # we expect that it is allocated from 81.00 as both VF on 81.01 is
        # reserved
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_1vf = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts('compute1', total=4, free=3)
        compute1_expected_placement_view["usages"] = {
            "0000:81:00.0": {"CUSTOM_MY_VF": 1}
        }
        compute1_expected_placement_view["allocations"][server_1vf["id"]] = {
            "0000:81:00.0": {"CUSTOM_MY_VF": 1},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assert_no_pci_healing("compute1")

        # Boot a second instance requesting two VFs and ensure that the only
        # way that placement allows this is to split the two VFs between PFs.
        # Let's remove the reservation of one resource from 81.01 so the only
        # viable placement candidate is: one VF from 81.00 and one VF from
        # 81.01
        self._reserve_placement_resource(
            "compute1_0000:81:01.0", "CUSTOM_MY_VF", 1)

        extra_spec = {"pci_passthrough:alias": "a-vf:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_2vf = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts('compute1', total=4, free=1)
        compute1_expected_placement_view["usages"] = {
            # both VM uses one VF
            "0000:81:00.0": {"CUSTOM_MY_VF": 2},
            "0000:81:01.0": {"CUSTOM_MY_VF": 1},
        }
        compute1_expected_placement_view["allocations"][server_2vf["id"]] = {
            "0000:81:00.0": {"CUSTOM_MY_VF": 1},
            "0000:81:01.0": {"CUSTOM_MY_VF": 1},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assert_no_pci_healing("compute1")

    def test_3vfs_asymmetric_split_between_pfs(self):
        # The fake libvirt will emulate on the host:
        # * two type-PFs in slot 0, 1 with 2 VFs each
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=2, num_vfs=4)
        # make all 4 VFs available
        device_spec = self._to_list_of_json_str(
            [
                {
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "resource_class": "MY_VF",
                    "traits": "blue",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        compute1_expected_placement_view = {
            "inventories": {
                "0000:81:00.0": {"CUSTOM_MY_VF": 2},
                "0000:81:01.0": {"CUSTOM_MY_VF": 2},
            },
            "traits": {
                "0000:81:00.0": [
                    "CUSTOM_BLUE",
                ],
                "0000:81:01.0": [
                    "CUSTOM_BLUE",
                ],
            },
            "usages": {
                "0000:81:00.0": {"CUSTOM_MY_VF": 0},
                "0000:81:01.0": {"CUSTOM_MY_VF": 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assertPCIDeviceCounts('compute1', total=4, free=4)

        pci_alias_vf = {
            "resource_class": "MY_VF",
            "traits": "blue",
            "name": "a-vf",
        }
        self.flags(
            group="pci",
            alias=self._to_list_of_json_str([pci_alias_vf]),
        )

        # Boot an instance requesting three VFs. The 3 VFs can be split between
        # the two PFs two ways: 2 from 81.00 and 1 from 81.01, or 1 from 81.00
        # and 2 from 81.01.
        # Let's block the first way in placement by reserving 1 device from
        # 81.00
        self._reserve_placement_resource(
            "compute1_0000:81:00.0", "CUSTOM_MY_VF", 1)
        extra_spec = {"pci_passthrough:alias": "a-vf:3"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        # We expect this to fit.
        server_3vf = self._create_server(flavor_id=flavor_id, networks=[])

        self.assertPCIDeviceCounts('compute1', total=4, free=1)
        compute1_expected_placement_view["usages"] = {
            "0000:81:00.0": {"CUSTOM_MY_VF": 1},
            "0000:81:01.0": {"CUSTOM_MY_VF": 2},
        }
        compute1_expected_placement_view["allocations"][server_3vf["id"]] = {
            "0000:81:00.0": {"CUSTOM_MY_VF": 1},
            "0000:81:01.0": {"CUSTOM_MY_VF": 2},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_expected_placement_view)
        self.assert_no_pci_healing("compute1")
