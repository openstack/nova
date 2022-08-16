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

"""Tests for PCI request."""

from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel

from nova import context
from nova import exception
from nova.network import model
from nova import objects
from nova.objects import fields
from nova.pci import request
from nova import test
from nova.tests.unit.api.openstack import fakes


_fake_alias1 = jsonutils.dumps({
    "name": "QuickAssist",
    "capability_type": "pci",
    "product_id": "4443",
    "vendor_id": "8086",
    "device_type": "type-PCI",
    "numa_policy": "legacy",
})

_fake_alias2 = jsonutils.dumps({
    "name": "IntelNIC",
    "capability_type": "pci",
    "product_id": "1111",
    "vendor_id": "8086",
    "device_type": "type-PF",
})


class PciRequestTestCase(test.NoDBTestCase):

    @staticmethod
    def _create_fake_inst_with_pci_devs(pci_req_list, pci_dev_list):
        """Create a fake Instance object with the provided InstancePciRequests
        and PciDevices.

        :param pci_req_list: a list of InstancePCIRequest objects.
        :param pci_dev_list: a list of PciDevice objects, each element
               associated (via request_id attribute)with a corresponding
               element from pci_req_list.
        :return: A fake Instance object associated with the provided
                 PciRequests and PciDevices.
        """

        inst = objects.Instance()
        inst.uuid = uuidsentinel.instance1
        inst.pci_requests = objects.InstancePCIRequests(
            requests=pci_req_list)
        inst.pci_devices = objects.PciDeviceList(objects=pci_dev_list)
        inst.host = 'fake-host'
        inst.node = 'fake-node'
        return inst

    def setUp(self):
        super(PciRequestTestCase, self).setUp()
        self.context = context.RequestContext(fakes.FAKE_USER_ID,
                                              fakes.FAKE_PROJECT_ID)

    def test_get_alias_from_config_valid(self):
        self.flags(alias=[_fake_alias1], group='pci')
        result = request._get_alias_from_config()
        expected_result = (
            'legacy',
            [{
                "capability_type": "pci",
                "product_id": "4443",
                "vendor_id": "8086",
                "dev_type": "type-PCI",
            }])
        self.assertEqual(expected_result, result['QuickAssist'])

    def test_get_alias_from_config_valid_multispec(self):
        _fake_alias = jsonutils.dumps({
            "name": "QuickAssist",
            "capability_type": "pci",
            "product_id": "4444",
            "vendor_id": "8086",
            "device_type": "type-PCI",
        })

        self.flags(alias=[_fake_alias1, _fake_alias], group='pci')
        result = request._get_alias_from_config()
        expected_result = (
            'legacy',
            [{
                "capability_type": "pci",
                "product_id": "4443",
                "vendor_id": "8086",
                "dev_type": "type-PCI"
            }, {
                "capability_type": "pci",
                "product_id": "4444",
                "vendor_id": "8086",
                "dev_type": "type-PCI"
            }])
        self.assertEqual(expected_result, result['QuickAssist'])

    def _test_get_alias_from_config_invalid(self, alias):
        self.flags(alias=[alias], group='pci')
        self.assertRaises(
            exception.PciInvalidAlias,
            request._get_alias_from_config)

    def test_get_alias_from_config_invalid_device_type(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "device_type": "N",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_device_type_vdpa(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "device_type": "vdpa",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_invalid_product_id(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "product_id": "g111",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_invalid_vendor_id(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "vendor_id": "0xg111",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_invalid_capability_type(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "capability_type": "usb",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_invalid_numa_policy(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "numa_policy": "derp",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_invalid_arbitrary_field(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "foo": "bar",
        })
        self._test_get_alias_from_config_invalid(fake_alias)

    def test_get_alias_from_config_valid_numa_policy(self):
        for policy in fields.PCINUMAAffinityPolicy.ALL:
            fake_alias = jsonutils.dumps({
                "name": "xxx",
                "capability_type": "pci",
                "product_id": "1111",
                "vendor_id": "8086",
                "device_type": "type-PCI",
                "numa_policy": policy,
            })
            self.flags(alias=[fake_alias], group='pci')
            aliases = request._get_alias_from_config()
            self.assertIsNotNone(aliases)
            self.assertIn("xxx", aliases)
            self.assertEqual(policy, aliases["xxx"][0])

    def test_get_alias_from_config_valid_rc_and_traits(self):
        fake_alias = jsonutils.dumps({
            "name": "xxx",
            "resource_class": "foo",
            "traits": "bar,baz",
        })
        self.flags(alias=[fake_alias], group='pci')
        aliases = request._get_alias_from_config()
        self.assertIsNotNone(aliases)
        self.assertIn("xxx", aliases)
        self.assertEqual(
            ("legacy", [{"resource_class": "foo", "traits": "bar,baz"}]),
            aliases["xxx"],
        )

    def test_get_alias_from_config_conflicting_device_type(self):
        """Check behavior when device_type conflicts occur."""
        fake_alias_a = jsonutils.dumps({
            "name": "xxx",
            "capability_type": "pci",
            "product_id": "1111",
            "vendor_id": "8086",
            "device_type": "type-PF"
        })
        fake_alias_b = jsonutils.dumps({
            "name": "xxx",
            "capability_type": "pci",
            "product_id": "1111",
            "vendor_id": "8086",
            "device_type": "type-PCI"
        })

        self.flags(alias=[fake_alias_a, fake_alias_b], group='pci')
        self.assertRaises(
            exception.PciInvalidAlias,
            request._get_alias_from_config)

    def test_get_alias_from_config_conflicting_numa_policy(self):
        """Check behavior when numa_policy conflicts occur."""
        fake_alias_a = jsonutils.dumps({
            "name": "xxx",
            "capability_type": "pci",
            "product_id": "1111",
            "vendor_id": "8086",
            "numa_policy": "required",
        })
        fake_alias_b = jsonutils.dumps({
            "name": "xxx",
            "capability_type": "pci",
            "product_id": "1111",
            "vendor_id": "8086",
            "numa_policy": "legacy",
        })
        self.flags(alias=[fake_alias_a, fake_alias_b], group='pci')
        self.assertRaises(
            exception.PciInvalidAlias,
            request._get_alias_from_config)

    def _verify_result(self, expected, real):
        exp_real = zip(expected, real)
        for exp, real in exp_real:
            self.assertEqual(exp['count'], real.count)
            self.assertEqual(exp['alias_name'], real.alias_name)
            self.assertEqual(exp['spec'], real.spec)

    def test_translate_alias_to_requests(self):
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        expect_request = [
            {'count': 3,
             'requester_id': None,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'dev_type': 'type-PCI',
                       'capability_type': 'pci'}],
                       'alias_name': 'QuickAssist'},

            {'count': 1,
             'requester_id': None,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'dev_type': "type-PF",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        requests = request._translate_alias_to_requests(
            "QuickAssist : 3, IntelNIC: 1")
        self.assertEqual(set([p.count for p in requests]), set([1, 3]))
        self._verify_result(expect_request, requests)

    def test_translate_alias_to_requests_invalid(self):
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        self.assertRaises(exception.PciRequestAliasNotDefined,
                          request._translate_alias_to_requests,
                          "QuickAssistX : 3")

    def test_translate_alias_to_requests_affinity_policy(self):
        # _fake_alias1 requests the legacy policy and _fake_alias2
        # has no numa_policy set so it will default to legacy.
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        # so to test that the flavor/image policy takes precedence
        # set use the preferred policy.
        policy = fields.PCINUMAAffinityPolicy.PREFERRED
        expect_request = [
            {'count': 3,
             'requester_id': None,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'dev_type': 'type-PCI',
                       'capability_type': 'pci'}],
             'alias_name': 'QuickAssist',
             'numa_policy': policy
             },

            {'count': 1,
             'requester_id': None,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'dev_type': "type-PF",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC',
             'numa_policy': policy
             }, ]

        requests = request._translate_alias_to_requests(
            "QuickAssist : 3, IntelNIC: 1", affinity_policy=policy)
        self.assertEqual(set([p.count for p in requests]), set([1, 3]))
        self._verify_result(expect_request, requests)

    @mock.patch.object(objects.compute_node.ComputeNode,
                       'get_by_host_and_nodename')
    def test_get_instance_pci_request_from_vif_invalid(
            self,
            cn_get_by_host_and_node):
        # Basically make sure we raise an exception if an instance
        # has an allocated PCI device without having the its corresponding
        # PCIRequest object in instance.pci_requests
        mock_inst_cn = mock.Mock()
        mock_inst_cn.id = 1
        cn_get_by_host_and_node.return_value = mock_inst_cn

        # Create a fake instance with PCI request and allocated PCI devices
        pci_dev1 = objects.PciDevice(request_id=uuidsentinel.pci_req_id1,
                                     address='0000:04:00.0',
                                     compute_node_id=1)

        pci_req2 = objects.InstancePCIRequest(
            request_id=uuidsentinel.pci_req_id2)
        pci_dev2 = objects.PciDevice(request_id=uuidsentinel.pci_req_id2,
                                     address='0000:05:00.0',
                                     compute_node_id=1)
        pci_request_list = [pci_req2]
        pci_device_list = [pci_dev1, pci_dev2]
        inst = PciRequestTestCase._create_fake_inst_with_pci_devs(
            pci_request_list,
            pci_device_list)
        # Create a VIF with pci_dev1 that has no corresponding PCI request
        pci_vif = model.VIF(vnic_type=model.VNIC_TYPE_DIRECT,
                            profile={'pci_slot': '0000:04:00.0'})

        self.assertRaises(exception.PciRequestFromVIFNotFound,
                          request.get_instance_pci_request_from_vif,
                          self.context,
                          inst,
                          pci_vif)

    @mock.patch.object(objects.compute_node.ComputeNode,
                       'get_by_host_and_nodename')
    def test_get_instance_pci_request_from_vif(self, cn_get_by_host_and_node):
        mock_inst_cn = mock.Mock()
        mock_inst_cn.id = 1
        cn_get_by_host_and_node.return_value = mock_inst_cn

        # Create a fake instance with PCI request and allocated PCI devices
        pci_req1 = objects.InstancePCIRequest(
            request_id=uuidsentinel.pci_req_id1)
        pci_dev1 = objects.PciDevice(request_id=uuidsentinel.pci_req_id1,
                                     address='0000:04:00.0',
                                     compute_node_id = 1)
        pci_req2 = objects.InstancePCIRequest(
            request_id=uuidsentinel.pci_req_id2)
        pci_dev2 = objects.PciDevice(request_id=uuidsentinel.pci_req_id2,
                                     address='0000:05:00.0',
                                     compute_node_id=1)
        pci_request_list = [pci_req1, pci_req2]
        pci_device_list = [pci_dev1, pci_dev2]
        inst = PciRequestTestCase._create_fake_inst_with_pci_devs(
            pci_request_list,
            pci_device_list)

        # Create a vif with normal port and make sure no PCI request returned
        normal_vif = model.VIF(vnic_type=model.VNIC_TYPE_NORMAL)
        self.assertIsNone(request.get_instance_pci_request_from_vif(
            self.context,
            inst,
            normal_vif))

        # Create a vif with PCI address under profile, make sure the correct
        # PCI request is returned
        pci_vif = model.VIF(vnic_type=model.VNIC_TYPE_DIRECT,
                            profile={'pci_slot': '0000:05:00.0'})
        self.assertEqual(uuidsentinel.pci_req_id2,
                         request.get_instance_pci_request_from_vif(
                             self.context,
                             inst,
                             pci_vif).request_id)

        # Create a vif with PCI under profile which is not claimed
        # for the instance, i.e no matching pci device in instance.pci_devices
        nonclaimed_pci_vif = model.VIF(vnic_type=model.VNIC_TYPE_DIRECT,
                                       profile={'pci_slot': '0000:08:00.0'})
        self.assertIsNone(request.get_instance_pci_request_from_vif(
            self.context,
            inst,
            nonclaimed_pci_vif))

        # "Move" the instance to another compute node, make sure that no
        # matching PCI request against the new compute.
        mock_inst_cn.id = 2
        self.assertIsNone(request.get_instance_pci_request_from_vif(
            self.context,
            inst,
            pci_vif))

    def test_get_pci_requests_from_flavor(self):
        self.flags(alias=[_fake_alias1], group='pci')
        expect_request = [
            {
                'count': 3,
                'spec': [
                    {
                        'vendor_id': '8086',
                        'product_id': '4443',
                        'dev_type': "type-PCI",
                        'capability_type': 'pci',
                    }
                ],
                'alias_name': 'QuickAssist'
            },
        ]

        flavor = {'extra_specs': {'pci_passthrough:alias': 'QuickAssist:3'}}
        requests = request.get_pci_requests_from_flavor(flavor)
        self.assertEqual(1, len(requests.requests))
        self.assertEqual({3, }, {p.count for p in requests.requests})
        self._verify_result(expect_request, requests.requests)

    def test_get_pci_requests_from_flavor_multiple(self):
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        expect_request = [
            {'count': 3,
             'spec': [{'vendor_id': '8086', 'product_id': '4443',
                       'dev_type': "type-PCI",
                       'capability_type': 'pci'}],
             'alias_name': 'QuickAssist'},

            {'count': 1,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'dev_type': "type-PF",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        flavor = {'extra_specs': {"pci_passthrough:alias":
                                  "QuickAssist:3, IntelNIC: 1"}}
        requests = request.get_pci_requests_from_flavor(flavor)
        self.assertEqual(2, len(requests.requests))
        self.assertEqual({3, 1}, {p.count for p in requests.requests})
        self._verify_result(expect_request, requests.requests)

    def test_get_pci_requests_from_flavor_including_space(self):
        _fake_alias4 = jsonutils.dumps({
            "name": " Cirrus Logic ",
            "capability_type": "pci",
            "product_id": "0ff2",
            "vendor_id": "10de",
            "device_type": "type-PCI",
        })

        self.flags(alias=[_fake_alias2, _fake_alias4], group='pci')
        expect_request = [
            {'count': 4,
             'spec': [{'vendor_id': '10de', 'product_id': '0ff2',
                       'dev_type': "type-PCI",
                       'capability_type': 'pci'}],
             'alias_name': 'Cirrus Logic'},

            {'count': 3,
             'spec': [{'vendor_id': '8086', 'product_id': '1111',
                       'dev_type': "type-PF",
                       'capability_type': 'pci'}],
             'alias_name': 'IntelNIC'}, ]

        flavor = {'extra_specs': {"pci_passthrough:alias":
                                  " Cirrus Logic : 4, IntelNIC: 3"}}
        requests = request.get_pci_requests_from_flavor(flavor)
        self.assertEqual(2, len(requests.requests))
        self.assertEqual({3, 4}, {p.count for p in requests.requests})
        self._verify_result(expect_request, requests.requests)

    def test_get_pci_requests_from_flavor_no_extra_spec(self):
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        flavor = {}
        requests = request.get_pci_requests_from_flavor(flavor)
        self.assertEqual([], requests.requests)

    @mock.patch.object(
        request, "_translate_alias_to_requests", return_value=[])
    def test_get_pci_requests_from_flavor_affinity_policy(
            self, mock_translate):
        self.flags(alias=[_fake_alias1, _fake_alias2], group='pci')
        flavor = {'extra_specs': {"pci_passthrough:alias":
                                  "QuickAssist:3, IntelNIC: 1"}}
        policy = fields.PCINUMAAffinityPolicy.PREFERRED
        request.get_pci_requests_from_flavor(flavor, affinity_policy=policy)
        mock_translate.assert_called_with(mock.ANY, affinity_policy=policy)
