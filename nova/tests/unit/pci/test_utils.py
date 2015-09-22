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

import glob
import os

import mock
from six.moves import builtins

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


class GetFunctionByIfnameTestCase(test.NoDBTestCase):

    @mock.patch('os.path.isdir', return_value=True)
    @mock.patch.object(os, 'readlink')
    def test_virtual_function(self, mock_readlink, *args):
        mock_readlink.return_value = '../../../0000.00.00.1'
        with mock.patch.object(
            builtins, 'open', side_effect=IOError()):
            address, physical_function = utils.get_function_by_ifname('eth0')
            self.assertEqual(address, '0000.00.00.1')
            self.assertFalse(physical_function)

    @mock.patch('os.path.isdir', return_value=True)
    @mock.patch.object(os, 'readlink')
    def test_physical_function(self, mock_readlink, *args):
        mock_readlink.return_value = '../../../0000:00:00.1'
        with mock.patch.object(
            builtins, 'open', mock.mock_open(read_data='4')):
            address, physical_function = utils.get_function_by_ifname('eth0')
            self.assertEqual(address, '0000:00:00.1')
            self.assertTrue(physical_function)

    @mock.patch('os.path.isdir', return_value=False)
    def test_exception(self, *args):
        address, physical_function = utils.get_function_by_ifname('lo')
        self.assertIsNone(address)
        self.assertFalse(physical_function)


class IsPhysicalFunctionTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IsPhysicalFunctionTestCase, self).setUp()
        self.pci_args = utils.get_pci_address_fields('0000:00:00.1')

    @mock.patch('os.path.isdir', return_value=True)
    def test_virtual_function(self, *args):
        with mock.patch.object(
            builtins, 'open', side_effect=IOError()):
            self.assertFalse(utils.is_physical_function(*self.pci_args))

    @mock.patch('os.path.isdir', return_value=True)
    def test_physical_function(self, *args):
        with mock.patch.object(
            builtins, 'open', mock.mock_open(read_data='4')):
            self.assertTrue(utils.is_physical_function(*self.pci_args))

    @mock.patch('os.path.isdir', return_value=False)
    def test_exception(self, *args):
        self.assertFalse(utils.is_physical_function(*self.pci_args))


class GetIfnameByPciAddressTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GetIfnameByPciAddressTestCase, self).setUp()
        self.pci_address = '0000:00:00.1'

    @mock.patch.object(os, 'listdir')
    def test_physical_function_inferface_name(self, mock_listdir):
        mock_listdir.return_value = ['foo', 'bar']
        ifname = utils.get_ifname_by_pci_address(
            self.pci_address, pf_interface=True)
        self.assertEqual(ifname, 'bar')

    @mock.patch.object(os, 'listdir')
    def test_virtual_function_inferface_name(self, mock_listdir):
        mock_listdir.return_value = ['foo', 'bar']
        ifname = utils.get_ifname_by_pci_address(
            self.pci_address, pf_interface=False)
        self.assertEqual(ifname, 'bar')

    @mock.patch.object(os, 'listdir')
    def test_exception(self, mock_listdir):
        mock_listdir.side_effect = OSError('No such file or directory')
        self.assertRaises(
            exception.PciDeviceNotFoundById,
            utils.get_ifname_by_pci_address,
            self.pci_address
        )


class GetVfNumByPciAddressTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GetVfNumByPciAddressTestCase, self).setUp()
        self.pci_address = '0000:00:00.1'
        self.paths = [
            '/sys/bus/pci/devices/0000:00:00.1/physfn/virtfn3',
        ]

    @mock.patch.object(os, 'readlink')
    @mock.patch.object(glob, 'iglob')
    def test_vf_number_found(self, mock_iglob, mock_readlink):
        mock_iglob.return_value = self.paths
        mock_readlink.return_value = '../../0000:00:00.1'
        vf_num = utils.get_vf_num_by_pci_address(self.pci_address)
        self.assertEqual(vf_num, '3')

    @mock.patch.object(os, 'readlink')
    @mock.patch.object(glob, 'iglob')
    def test_vf_number_not_found(self, mock_iglob, mock_readlink):
        mock_iglob.return_value = self.paths
        mock_readlink.return_value = '../../0000:00:00.2'
        self.assertRaises(
            exception.PciDeviceNotFoundById,
            utils.get_vf_num_by_pci_address,
            self.pci_address
        )

    @mock.patch.object(os, 'readlink')
    @mock.patch.object(glob, 'iglob')
    def test_exception(self, mock_iglob, mock_readlink):
        mock_iglob.return_value = self.paths
        mock_readlink.side_effect = OSError('No such file or directory')
        self.assertRaises(
            exception.PciDeviceNotFoundById,
            utils.get_vf_num_by_pci_address,
            self.pci_address
        )
