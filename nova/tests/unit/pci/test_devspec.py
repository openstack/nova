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


import mock
import six

from nova import exception
from nova import objects
from nova.pci import devspec
from nova import test

dev = {"vendor_id": "8086",
       "product_id": "5057",
       "address": "1234:5678:8988.5",
       "parent_addr": "0000:0a:00.0"}


class PciAddressTestCase(test.NoDBTestCase):
    def test_wrong_address(self):
        pci_info = {"vendor_id": "8086", "address": "*: *: *.6",
                    "product_id": "5057", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertFalse(pci.match(dev))

    def test_address_too_big(self):
        pci_info = {"address": "0000:0a:0b:00.5",
                    "physical_network": "hr_net"}
        self.assertRaises(exception.PciDeviceWrongAddressFormat,
            devspec.PciDeviceSpec, pci_info)

    def test_address_invalid_character(self):
        pci_info = {"address": "0000:h4.12:6", "physical_network": "hr_net"}
        self.assertRaises(exception.PciDeviceWrongAddressFormat,
            devspec.PciDeviceSpec, pci_info)

    def test_max_func(self):
        pci_info = {"address": "0000:0a:00.%s" % (devspec.MAX_FUNC + 1),
                    "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciDeviceInvalidAddressField,
                  devspec.PciDeviceSpec, pci_info)
        msg = ('Invalid PCI Whitelist: '
               'The PCI address 0000:0a:00.%s has an invalid function.'
                  % (devspec.MAX_FUNC + 1))
        self.assertEqual(msg, six.text_type(exc))

    def test_max_domain(self):
        pci_info = {"address": "%x:0a:00.5" % (devspec.MAX_DOMAIN + 1),
                    "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciConfigInvalidWhitelist,
                  devspec.PciDeviceSpec, pci_info)
        msg = ('Invalid PCI devices Whitelist config invalid domain %x'
               % (devspec.MAX_DOMAIN + 1))
        self.assertEqual(msg, six.text_type(exc))

    def test_max_bus(self):
        pci_info = {"address": "0000:%x:00.5" % (devspec.MAX_BUS + 1),
                    "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciConfigInvalidWhitelist,
                  devspec.PciDeviceSpec, pci_info)
        msg = ('Invalid PCI devices Whitelist config invalid bus %x'
               % (devspec.MAX_BUS + 1))
        self.assertEqual(msg, six.text_type(exc))

    def test_max_slot(self):
        pci_info = {"address": "0000:0a:%x.5" % (devspec.MAX_SLOT + 1),
                    "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciConfigInvalidWhitelist,
                  devspec.PciDeviceSpec, pci_info)
        msg = ('Invalid PCI devices Whitelist config invalid slot %x'
               % (devspec.MAX_SLOT + 1))
        self.assertEqual(msg, six.text_type(exc))

    def test_address_is_undefined(self):
        pci_info = {"vendor_id": "8086", "product_id": "5057"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertTrue(pci.match(dev))

    def test_partial_address(self):
        pci_info = {"address": ":0a:00.", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        dev = {"vendor_id": "1137",
               "product_id": "0071",
               "address": "0000:0a:00.5",
               "parent_addr": "0000:0a:00.0"}
        self.assertTrue(pci.match(dev))

    @mock.patch('nova.pci.utils.is_physical_function', return_value = True)
    def test_address_is_pf(self, mock_is_physical_function):
        pci_info = {"address": "0000:0a:00.0", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertTrue(pci.match(dev))


class PciDevSpecTestCase(test.NoDBTestCase):
    def test_spec_match(self):
        pci_info = {"vendor_id": "8086", "address": "*: *: *.5",
                    "product_id": "5057", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertTrue(pci.match(dev))

    def test_invalid_vendor_id(self):
        pci_info = {"vendor_id": "8087", "address": "*: *: *.5",
                    "product_id": "5057", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertFalse(pci.match(dev))

    def test_vendor_id_out_of_range(self):
        pci_info = {"vendor_id": "80860", "address": "*:*:*.5",
                    "product_id": "5057", "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciConfigInvalidWhitelist,
                                devspec.PciDeviceSpec, pci_info)
        self.assertEqual("Invalid PCI devices Whitelist config "
                         "invalid vendor_id 80860", six.text_type(exc))

    def test_invalid_product_id(self):
        pci_info = {"vendor_id": "8086", "address": "*: *: *.5",
                    "product_id": "5056", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertFalse(pci.match(dev))

    def test_product_id_out_of_range(self):
        pci_info = {"vendor_id": "8086", "address": "*:*:*.5",
                    "product_id": "50570", "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciConfigInvalidWhitelist,
                                devspec.PciDeviceSpec, pci_info)
        self.assertEqual("Invalid PCI devices Whitelist config "
                         "invalid product_id 50570", six.text_type(exc))

    def test_devname_and_address(self):
        pci_info = {"devname": "eth0", "vendor_id": "8086",
                    "address": "*:*:*.5", "physical_network": "hr_net"}
        self.assertRaises(exception.PciDeviceInvalidDeviceName,
                          devspec.PciDeviceSpec, pci_info)

    @mock.patch('nova.pci.utils.get_function_by_ifname',
        return_value = ("0000:0a:00.0", True))
    def test_by_name(self, mock_get_function_by_ifname):
        pci_info = {"devname": "eth0", "physical_network": "hr_net"}
        pci = devspec.PciDeviceSpec(pci_info)
        self.assertTrue(pci.match(dev))

    @mock.patch('nova.pci.utils.get_function_by_ifname',
        return_value = (None, False))
    def test_invalid_name(self, mock_get_function_by_ifname):
        pci_info = {"devname": "lo", "physical_network": "hr_net"}
        exc = self.assertRaises(exception.PciDeviceNotFoundById,
                  devspec.PciDeviceSpec, pci_info)
        self.assertEqual('PCI device lo not found', six.text_type(exc))

    def test_pci_obj(self):
        pci_info = {"vendor_id": "8086", "address": "*:*:*.5",
                    "product_id": "5057", "physical_network": "hr_net"}

        pci = devspec.PciDeviceSpec(pci_info)
        pci_dev = {
            'compute_node_id': 1,
            'address': '0000:00:00.5',
            'product_id': '5057',
            'vendor_id': '8086',
            'status': 'available',
            'parent_addr': None,
            'extra_k1': 'v1',
        }

        pci_obj = objects.PciDevice.create(None, pci_dev)
        self.assertTrue(pci.match_pci_obj(pci_obj))
