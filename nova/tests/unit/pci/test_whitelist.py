# Copyright (c) 2012 OpenStack Foundation
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

from nova.pci import whitelist
from nova import test


dev_dict = {
    'compute_node_id': 1,
    'address': '0000:00:0a.1',
    'product_id': '0001',
    'vendor_id': '8086',
    'status': 'available',
    'phys_function': '0000:00:0a.0',
    }


class PciHostDevicesWhiteListTestCase(test.NoDBTestCase):
    def test_whitelist(self):
        white_list = '{"product_id":"0001", "vendor_id":"8086"}'
        parsed = whitelist.PciHostDevicesWhiteList([white_list])
        self.assertEqual(1, len(parsed.specs))

    def test_whitelist_list_format(self):
        white_list = '[{"product_id":"0001", "vendor_id":"8086"},'\
                       '{"product_id":"0002", "vendor_id":"8086"}]'
        parsed = whitelist.PciHostDevicesWhiteList([white_list])
        self.assertEqual(2, len(parsed.specs))

    def test_whitelist_empty(self):
        parsed = whitelist.PciHostDevicesWhiteList()
        self.assertFalse(parsed.device_assignable(dev_dict))

    def test_whitelist_multiple(self):
        wl1 = '{"product_id":"0001", "vendor_id":"8086"}'
        wl2 = '{"product_id":"0002", "vendor_id":"8087"}'
        parsed = whitelist.PciHostDevicesWhiteList([wl1, wl2])
        self.assertEqual(2, len(parsed.specs))

    def test_device_assignable(self):
        white_list = '{"product_id":"0001", "vendor_id":"8086"}'
        parsed = whitelist.PciHostDevicesWhiteList([white_list])
        self.assertIsNotNone(parsed.device_assignable(dev_dict))

    def test_device_assignable_multiple(self):
        white_list_1 = '{"product_id":"0001", "vendor_id":"8086"}'
        white_list_2 = '{"product_id":"0002", "vendor_id":"8087"}'
        parsed = whitelist.PciHostDevicesWhiteList(
            [white_list_1, white_list_2])
        self.assertIsNotNone(parsed.device_assignable(dev_dict))
        dev_dict1 = dev_dict.copy()
        dev_dict1['vendor_id'] = '8087'
        dev_dict1['product_id'] = '0002'
        self.assertIsNotNone(parsed.device_assignable(dev_dict1))

    def test_get_pci_devices_filter(self):
        white_list_1 = '{"product_id":"0001", "vendor_id":"8086"}'
        self.flags(pci_passthrough_whitelist=[white_list_1])
        pci_filter = whitelist.get_pci_devices_filter()
        self.assertIsNotNone(pci_filter.device_assignable(dev_dict))
