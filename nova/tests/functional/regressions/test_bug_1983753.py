# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import fixtures

from oslo_serialization import jsonutils

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_sriov_servers


class TestPciResize(test_pci_sriov_servers._PCIServersTestBase):
    # these tests use multiple different configs so the whitelist is set by
    # each testcase individually
    PCI_PASSTHROUGH_WHITELIST = []
    PCI_ALIAS = [
        jsonutils.dumps(x)
        for x in [
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
        ]
    ]

    def setUp(self):
        super().setUp()
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.'
                'migrate_disk_and_power_off',
                return_value='{}'
            )
        )
        # These tests should not depend on the host's sysfs
        self.useFixture(
            fixtures.MockPatch('nova.pci.utils.is_physical_function'))
        self.useFixture(
            fixtures.MockPatch(
                'nova.pci.utils.get_function_by_ifname',
                return_value=(None, False)
            )
        )

    def _test_resize_from_two_devs_to_one_dev(self, num_pci_on_dest):
        # The fake libvirt will emulate on the host:
        # * two type-PCI in slot 0, 1
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=2)
        # the config matches the PCI dev
        compute1_device_spec = [
            jsonutils.dumps(x)
            for x in [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        ]
        self.flags(group='pci', passthrough_whitelist=compute1_device_spec)
        self.start_compute(hostname="compute1", pci_info=compute1_pci_info)
        self.assertPCIDeviceCounts("compute1", total=2, free=2)

        # create a server that requests two PCI devs
        extra_spec = {"pci_passthrough:alias": "a-pci-dev:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=2, free=0)

        # start another compute with a different amount of PCI dev available
        compute2_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=num_pci_on_dest)
        # the config matches the PCI dev
        compute2_device_spec = [
            jsonutils.dumps(x)
            for x in [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PCI_PROD_ID,
                },
            ]
        ]
        self.flags(group='pci', passthrough_whitelist=compute2_device_spec)
        self.start_compute(hostname="compute2", pci_info=compute2_pci_info)
        self.assertPCIDeviceCounts(
            "compute2", total=num_pci_on_dest, free=num_pci_on_dest)

        # resize the server to request only one PCI dev instead of the current
        # two. This should fit to compute2 having at least one dev
        extra_spec = {"pci_passthrough:alias": "a-pci-dev:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._resize_server(server, flavor_id=flavor_id)
        self._confirm_resize(server)
        self.assertPCIDeviceCounts("compute1", total=2, free=2)
        self.assertPCIDeviceCounts(
            "compute2", total=num_pci_on_dest, free=num_pci_on_dest - 1)

    def test_resize_from_two_devs_to_one_dev_dest_has_two_devs(self):
        self._test_resize_from_two_devs_to_one_dev(num_pci_on_dest=2)

    def test_resize_from_two_devs_to_one_dev_dest_has_one_dev(self):
        self._test_resize_from_two_devs_to_one_dev(num_pci_on_dest=1)

    def test_resize_from_vf_to_pf(self):
        # The fake libvirt will emulate on the host:
        # * one type-PF in slot 0 with one VF
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=1)
        # the config matches only the VF
        compute1_device_spec = [
            jsonutils.dumps(x)
            for x in [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                },
            ]
        ]
        self.flags(group='pci', passthrough_whitelist=compute1_device_spec)
        self.start_compute(hostname="compute1", pci_info=compute1_pci_info)
        self.assertPCIDeviceCounts("compute1", total=1, free=1)

        # create a server that requests one Vf
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self.assertPCIDeviceCounts("compute1", total=1, free=0)

        # start another compute with a single PF dev available
        # The fake libvirt will emulate on the host:
        # * one type-PF in slot 0 with 1 VF
        compute2_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=1)
        # the config matches the PF dev but not the VF
        compute2_device_spec = [
            jsonutils.dumps(x)
            for x in [
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                },
            ]
        ]
        self.flags(group='pci', passthrough_whitelist=compute2_device_spec)
        self.start_compute(hostname="compute2", pci_info=compute2_pci_info)
        self.assertPCIDeviceCounts("compute2", total=1, free=1)

        # resize the server to request on PF dev instead of the current VF
        # dev. This should fit to compute2 having exactly one PF dev.
        extra_spec = {"pci_passthrough:alias": "a-pf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._resize_server(server, flavor_id=flavor_id)
        self._confirm_resize(server)
        self.assertPCIDeviceCounts("compute1", total=1, free=1)
        self.assertPCIDeviceCounts("compute2", total=1, free=0)
