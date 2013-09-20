# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import exception
from nova.objects import pci_device
from nova.pci import pci_whitelist
from nova import test


dev_dict = {
    'compute_node_id': 1,
    'address': 'a',
    'product_id': '0001',
    'vendor_id': '8086',
    'status': 'available',
    }


class PciHostDevicesWhiteListTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PciHostDevicesWhiteListTestCase, self).setUp()

    def test_whitelist_wrong_format(self):
        white_list = '[{"vendor_x_id":"8086", "product_id":"0001"}]'
        self.assertRaises(
            exception.PciConfigInvalidWhitelist,
            pci_whitelist.PciHostDevicesWhiteList, white_list
        )

        white_list = '[{"vendor_id":"80863", "product_id":"0001"}]'
        self.assertRaises(
            exception.PciConfigInvalidWhitelist,
            pci_whitelist.PciHostDevicesWhiteList, white_list
        )

    def test_whitelist_missed_fields(self):
        white_list = '[{"vendor_id":"80863"}]'
        self.assertRaises(
            exception.PciConfigInvalidWhitelist,
            pci_whitelist.PciHostDevicesWhiteList, white_list
        )

    def test_whitelist(self):
        white_list = '[{"product_id":"0001", "vendor_id":"8086"}]'
        parsed = pci_whitelist.PciHostDevicesWhiteList([white_list])
        self.assertEqual(parsed.spec, [{'vendor_id': '8086',
                                        'product_id': '0001'}])

    def test_whitelist_empty(self):
        dev = pci_device.PciDevice.create(dev_dict)
        parsed = pci_whitelist.PciHostDevicesWhiteList()
        self.assertEqual(parsed.device_assignable(dev), False)

    def test_whitelist_multiple(self):
        white_list_1 = '[{"product_id":"0001", "vendor_id":"8086"}]'
        white_list_2 = '[{"product_id":"0002", "vendor_id":"8087"}]'
        parsed = pci_whitelist.PciHostDevicesWhiteList(
            [white_list_1, white_list_2])
        self.assertEqual(parsed.spec,
                        [{'vendor_id': '8086', 'product_id': '0001'},
                         {'vendor_id': '8087', 'product_id': '0002'}])

    def test_device_assignable(self):
        dev = pci_device.PciDevice.create(dev_dict)
        white_list = '[{"product_id":"0001", "vendor_id":"8086"}]'
        parsed = pci_whitelist.PciHostDevicesWhiteList([white_list])
        self.assertEqual(parsed.device_assignable(dev), True)

    def test_device_assignable_multiple(self):
        dev = pci_device.PciDevice.create(dev_dict)
        white_list_1 = '[{"product_id":"0001", "vendor_id":"8086"}]'
        white_list_2 = '[{"product_id":"0002", "vendor_id":"8087"}]'
        parsed = pci_whitelist.PciHostDevicesWhiteList(
            [white_list_1, white_list_2])
        self.assertEqual(parsed.device_assignable(dev), True)
        dev.vendor_id = '8087'
        dev.product_id = '0002'
        self.assertEqual(parsed.device_assignable(dev), True)

    def test_get_pci_devices_filter(self):
        white_list_1 = '[{"product_id":"0001", "vendor_id":"8086"}]'
        self.flags(pci_passthrough_whitelist=[white_list_1])
        pci_filter = pci_whitelist.get_pci_devices_filter()
        dev = pci_device.PciDevice.create(dev_dict)
        self.assertEqual(pci_filter.device_assignable(dev), True)
