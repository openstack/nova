# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import test_pci_in_placement as base


class MultipleSpecPerAliasWithPCIInPlacementTest(
    base.PlacementPCIReportingTests
):

    def test_alias_with_multiple_specs_not_supported(self):
        self.flags(group='filter_scheduler', pci_in_placement=True)

        pci_alias = [
            {
                "device_type": "type-VF",
                "vendor_id": fakelibvirt.PCI_VEND_ID,
                "product_id": "f000",
                "name": "a-vf",
            },
            {
                "device_type": "type-VF",
                "vendor_id": fakelibvirt.PCI_VEND_ID,
                "product_id": "f001",
                "name": "a-vf",
            }
        ]
        self.flags(
            group="pci",
            alias=self._to_list_of_json_str(pci_alias),
        )
        extra_spec = {"pci_passthrough:alias": "a-vf:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        exc = self.assertRaises(
            client.OpenStackApiException,
            self._create_server,
            flavor_id=flavor_id,
            networks=[],
        )
        # This is bug 2102038 as nova does not handle the internal ValueError
        # and therefore returns HTTP 500 instead of returning 400 Bad Request
        # with a message pointing to the unsupported alias config.
        self.assertEqual(500, exc.response.status_code)
