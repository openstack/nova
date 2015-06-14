# Copyright (c) 2013 Intel, Inc.
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
from nova.pci import utils
from nova import test


class PciDeviceMatchTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PciDeviceMatchTestCase, self).setUp()
        self.fake_pci_1 = {'vendor_id': 'v1',
                           'device_id': 'd1'}

    def test_single_spec_match(self):
        self.assertTrue(utils.pci_device_prop_match(
            self.fake_pci_1, [{'vendor_id': 'v1', 'device_id': 'd1'}]))

    def test_multiple_spec_match(self):
        self.assertTrue(utils.pci_device_prop_match(
            self.fake_pci_1,
            [{'vendor_id': 'v1', 'device_id': 'd1'},
             {'vendor_id': 'v3', 'device_id': 'd3'}]))

    def test_spec_dismatch(self):
        self.assertFalse(utils.pci_device_prop_match(
            self.fake_pci_1,
            [{'vendor_id': 'v4', 'device_id': 'd4'},
             {'vendor_id': 'v3', 'device_id': 'd3'}]))

    def test_spec_extra_key(self):
        self.assertFalse(utils.pci_device_prop_match(
            self.fake_pci_1,
            [{'vendor_id': 'v1', 'device_id': 'd1', 'wrong_key': 'k1'}]))


class PciDeviceAddressParserTestCase(test.NoDBTestCase):
    def test_parse_address(self):
        self.parse_result = utils.parse_address("0000:04:12.6")
        self.assertEqual(self.parse_result, ('0000', '04', '12', '6'))

    def test_parse_address_wrong(self):
        self.assertRaises(exception.PciDeviceWrongAddressFormat,
            utils.parse_address, "0000:04.12:6")

    def test_parse_address_invalid_character(self):
        self.assertRaises(exception.PciDeviceWrongAddressFormat,
            utils.parse_address, "0000:h4.12:6")
