# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Intel Corporation
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
# @author: Yongli He, Intel Corporation.

"""Tests for PCI request."""

from nova import exception
from nova.openstack.common import jsonutils
from nova.pci import pci_request as pci_request
from nova import test


_fake_alias1 = """{
               "name": "QuicAssist",
               "capability_type": "pci",
               "product_id": "4443",
               "vendor_id": "8086",
               "device_type": "ACCEL"
               }"""

_fake_alias11 = """{
               "name": "QuicAssist",
               "capability_type": "pci",
               "product_id": "4444",
               "vendor_id": "8086",
               "device_type": "ACCEL"
               }"""

_fake_alias2 = """{
               "name": "xxx",
               "capability_type": "pci",
               "product_id": "1111",
               "vendor_id": "1111",
               "device_type": "N"
               }"""

_fake_alias3 = """{
               "name": "IntelNIC",
               "capability_type": "pci",
               "product_id": "1111",
               "vendor_id": "8086",
               "device_type": "NIC"
               }"""


class AliasTestCase(test.TestCase):

    def setUp(self):
        super(AliasTestCase, self).setUp()

    def test_good_alias(self):
        self.flags(pci_alias=[_fake_alias1])
        als = pci_request._get_alias_from_config()
        self.assertEqual(type(als['QuicAssist']), list)
        expect_dict = {
            "capability_type": "pci",
            "product_id": "4443",
            "vendor_id": "8086",
            "device_type": "ACCEL"
            }
        self.assertEqual(expect_dict, als['QuicAssist'][0])

    def test_multispec_alias(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias11])
        als = pci_request._get_alias_from_config()
        self.assertEqual(type(als['QuicAssist']), list)
        expect_dict1 = {
            "capability_type": "pci",
            "product_id": "4443",
            "vendor_id": "8086",
            "device_type": "ACCEL"
            }
        expect_dict2 = {
            "capability_type": "pci",
            "product_id": "4444",
            "vendor_id": "8086",
            "device_type": "ACCEL"
            }

        self.assertEqual(expect_dict1, als['QuicAssist'][0])
        self.assertEqual(expect_dict2, als['QuicAssist'][1])

    def test_wrong_type_aliase(self):
        self.flags(pci_alias=[_fake_alias2])
        self.assertRaises(exception.PciInvalidAlias,
            pci_request._get_alias_from_config)

    def test_wrong_product_id_aliase(self):
        self.flags(pci_alias=[
            """{
                "name": "xxx",
                "capability_type": "pci",
                "product_id": "g111",
                "vendor_id": "1111",
                "device_type": "NIC"
                }"""])
        self.assertRaises(exception.PciInvalidAlias,
            pci_request._get_alias_from_config)

    def test_wrong_vendor_id_aliase(self):
        self.flags(pci_alias=[
            """{
                "name": "xxx",
                "capability_type": "pci",
                "product_id": "1111",
                "vendor_id": "0xg111",
                "device_type": "NIC"
                }"""])
        self.assertRaises(exception.PciInvalidAlias,
            pci_request._get_alias_from_config)

    def test_wrong_cap_type_aliase(self):
        self.flags(pci_alias=[
            """{
                "name": "xxx",
                "capability_type": "usb",
                "product_id": "1111",
                "vendor_id": "8086",
                "device_type": "NIC"
                }"""])
        self.assertRaises(exception.PciInvalidAlias,
            pci_request._get_alias_from_config)

    def test_dup_aliase(self):
        self.flags(pci_alias=[
            """{
                "name": "xxx",
                "capability_type": "pci",
                "product_id": "1111",
                "vendor_id": "8086",
                "device_type": "NIC"
                }""",
            """{
                "name": "xxx",
                "capability_type": "pci",
                "product_id": "1111",
                "vendor_id": "8086",
                "device_type": "ACCEL"
                }"""])
        self.assertRaises(
            exception.PciInvalidAlias,
            pci_request._get_alias_from_config)

    def test_aliase_2_request(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        expect_request = [
            {'count': 3,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'device_type': 'ACCEL',
                       'capability_type': 'pci'}],
                       'alias_name': 'QuicAssist'},

            {'count': 1,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'device_type': "NIC",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        requests = pci_request._translate_alias_to_requests(
            "QuicAssist : 3, IntelNIC: 1")
        self.assertEqual(set([p['count'] for p in requests]), set([1, 3]))
        exp_real = zip(expect_request, requests)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

    def test_aliase_2_request_invalid(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        self.assertRaises(exception.PciRequestAliasNotDefined,
                          pci_request._translate_alias_to_requests,
                          "QuicAssistX : 3")

    def test_get_pci_requests_from_flavor(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        expect_request = [
            {'count': 3,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'device_type': "ACCEL",
                       'capability_type': 'pci'}],
             'alias_name': 'QuicAssist'},

            {'count': 1,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'device_type': "NIC",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        flavor = {'extra_specs': {"pci_passthrough:alias":
                                  "QuicAssist:3, IntelNIC: 1"}}
        requests = pci_request.get_pci_requests_from_flavor(flavor)
        self.assertEqual(set([p['count'] for p in requests]), set([1, 3]))
        exp_real = zip(expect_request, requests)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

    def test_get_pci_requests_from_flavor_no_extra_spec(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        flavor = {}
        requests = pci_request.get_pci_requests_from_flavor(flavor)
        self.assertEqual([], requests)

    def test_get_instance_pci_requests_no_meta(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        instance = {}
        requests = pci_request.get_instance_pci_requests(instance)
        self.assertEqual([], requests)

    def test_get_instance_pci_requests_no_request(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        instance = {'system_metadata': {'a': 'b'}}
        requests = pci_request.get_instance_pci_requests(instance)
        self.assertEqual([], requests)

    def test_get_instance_pci_requests(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        expect_request = [{
            'count': 3,
            'spec': [{'vendor_id': '8086', 'product_id': '4443',
                      'device_type': "ACCEL",
                      'capability_type': 'pci'}],
            'alias_name': 'QuicAssist'}]

        instance = {"system_metadata": {"pci_requests":
                                        jsonutils.dumps(expect_request)}}
        requests = pci_request.get_instance_pci_requests(instance)
        exp_real = zip(expect_request, requests)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

    def test_get_instance_pci_requests_prefix(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        expect_request = [{
            'count': 3,
            'spec': [{'vendor_id': '8086', 'product_id': '4443',
                      'device_type': "ACCEL",
                      'capability_type': 'pci'}],
            'alias_name': 'QuicAssist'}]

        instance = {"system_metadata": {"new_pci_requests":
                                        jsonutils.dumps(expect_request)}}
        requests = pci_request.get_instance_pci_requests(instance, 'new_')
        exp_real = zip(expect_request, requests)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

    def test_save_flavor_pci_info(self):
        self.flags(pci_alias=[_fake_alias1, _fake_alias3])
        expect_request = [
            {'count': 3,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'device_type': "ACCEL",
                       'capability_type': 'pci'}],
             'alias_name': 'QuicAssist'},

            {'count': 1,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'device_type': "NIC",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        flavor = {'extra_specs': {"pci_passthrough:alias":
                                  "QuicAssist:3, IntelNIC: 1"}}

        meta = {}
        pci_request.save_flavor_pci_info(meta, flavor)

        real = jsonutils.loads(meta['pci_requests'])
        exp_real = zip(expect_request, real)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

        meta = {}
        pci_request.save_flavor_pci_info(meta, flavor, "old_")
        real = jsonutils.loads(meta['old_pci_requests'])
        exp_real = zip(expect_request, real)
        for exp, real in exp_real:
            self.assertEqual(real, exp)

    def test_delete_flavor_pci_info(self):
        meta = {"pci_requests": "fake", "old_pci_requests": "fake"}
        pci_request.delete_flavor_pci_info(meta, '')
        self.assertTrue('pci_requests' not in meta)
        pci_request.delete_flavor_pci_info(meta, 'old_')
        self.assertTrue('old_pci_requests' not in meta)
