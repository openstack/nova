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

from nova.tests.functional.api import client
from nova.tests.functional.libvirt import test_pci_in_placement as base


class MissingRCAndIdAliasWithPCIInPlacementTest(
    base.PlacementPCIReportingTests
):

    def test_alias_without_rc_or_vendor_product_id_is_not_supported(self):
        self.flags(group='filter_scheduler', pci_in_placement=True)

        pci_alias = [
            {
                "device_type": "type-VF",
                "name": "a-vf",
                "traits": "foo"
            },
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
        self.assertEqual(400, exc.response.status_code)
        self.assertIn(
            "The PCI alias(es) a-vf does not have vendor_id and product_id "
            "fields set or resource_class field set.",
            exc.response.text)
