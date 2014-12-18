# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

import copy

from nova import objects
from nova.objects import pci_device_pool
from nova import test
from nova.tests.unit import fake_pci_device_pools as fake_pci
from nova.tests.unit.objects import test_objects


class _TestPciDevicePoolObject(object):

    def test_pci_pool_from_dict_not_distructive(self):
        test_dict = copy.copy(fake_pci.fake_pool_dict)
        objects.PciDevicePool.from_dict(test_dict)
        self.assertEqual(fake_pci.fake_pool_dict, test_dict)

    def test_pci_pool_from_dict(self):
        pool_obj = objects.PciDevicePool.from_dict(fake_pci.fake_pool_dict)
        self.assertEqual(pool_obj.product_id, 'fake-product')
        self.assertEqual(pool_obj.vendor_id, 'fake-vendor')
        self.assertEqual(pool_obj.tags, {'t1': 'v1', 't2': 'v2'})
        self.assertEqual(pool_obj.count, 2)

    def test_pci_pool_from_dict_no_tags(self):
        dict_notag = copy.copy(fake_pci.fake_pool_dict)
        dict_notag.pop('t1')
        dict_notag.pop('t2')
        pool_obj = objects.PciDevicePool.from_dict(dict_notag)
        self.assertEqual(pool_obj.tags, {})


class TestPciDevicePoolObject(test_objects._LocalTest,
                              _TestPciDevicePoolObject):
    pass


class TestRemotePciDevicePoolObject(test_objects._RemoteTest,
                                    _TestPciDevicePoolObject):
    pass


class TestConvertPciStats(test.NoDBTestCase):
    def test_from_pci_stats_obj(self):
        prim = fake_pci.fake_pool_list_primitive
        pools = pci_device_pool.from_pci_stats(prim)
        self.assertIsInstance(pools, pci_device_pool.PciDevicePoolList)
        self.assertEqual(len(pools), 1)

    def test_from_pci_stats_dict(self):
        prim = fake_pci.fake_pool_dict
        pools = pci_device_pool.from_pci_stats(prim)
        self.assertIsInstance(pools, pci_device_pool.PciDevicePoolList)
        self.assertEqual(len(pools), 1)

    def test_from_pci_stats_list_of_dicts(self):
        prim = fake_pci.fake_pool_dict
        pools = pci_device_pool.from_pci_stats([prim, prim])
        self.assertIsInstance(pools, pci_device_pool.PciDevicePoolList)
        self.assertEqual(len(pools), 2)

    def test_from_pci_stats_bad(self):
        prim = "not a valid json string for an object"
        pools = pci_device_pool.from_pci_stats(prim)
        self.assertIsNone(pools)
