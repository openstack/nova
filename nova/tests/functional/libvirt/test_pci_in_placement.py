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
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

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
        patcher.start()

        # These tests should not depend on the host's sysfs
        self.useFixture(
            fixtures.MockPatch('nova.pci.utils.is_physical_function'))

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
                },
                # PF_PROD_ID + slot 2 will match one PF but not their children
                # VFs
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.PF_PROD_ID,
                    "address": "0000:81:02.0",
                },
                # VF_PROD_ID + slot 3 will match two VFs but not their parent
                # PF
                {
                    "vendor_id": fakelibvirt.PCI_VEND_ID,
                    "product_id": fakelibvirt.VF_PROD_ID,
                    "address": "0000:81:03.*",
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
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
                "0000:81:03.0": [],
            },
        )
