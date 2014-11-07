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

import mock
from oslo.serialization import jsonutils

from nova import exception
from nova import objects
from nova.pci import stats
from nova.pci import whitelist
from nova import test
from nova.tests.unit.pci import fakes

fake_pci_1 = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p1',
    'vendor_id': 'v1',
    'status': 'available',
    'extra_k1': 'v1',
    'request_id': None,
    }


fake_pci_2 = dict(fake_pci_1, vendor_id='v2',
                  product_id='p2',
                  address='0000:00:00.2')


fake_pci_3 = dict(fake_pci_1, address='0000:00:00.3')


pci_requests = [objects.InstancePCIRequest(count=1,
                    spec=[{'vendor_id': 'v1'}]),
                objects.InstancePCIRequest(count=1,
                    spec=[{'vendor_id': 'v2'}])]


pci_requests_multiple = [objects.InstancePCIRequest(count=1,
                             spec=[{'vendor_id': 'v1'}]),
                         objects.InstancePCIRequest(count=3,
                          spec=[{'vendor_id': 'v2'}])]


class PciDeviceStatsTestCase(test.NoDBTestCase):
    def _create_fake_devs(self):
        self.fake_dev_1 = objects.PciDevice.create(fake_pci_1)
        self.fake_dev_2 = objects.PciDevice.create(fake_pci_2)
        self.fake_dev_3 = objects.PciDevice.create(fake_pci_3)

        map(self.pci_stats.add_device,
            [self.fake_dev_1, self.fake_dev_2, self.fake_dev_3])

    def setUp(self):
        super(PciDeviceStatsTestCase, self).setUp()
        self.pci_stats = stats.PciDeviceStats()
        # The following two calls need to be made before adding the devices.
        patcher = fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)
        self._create_fake_devs()

    def test_add_device(self):
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(set([d['vendor_id'] for d in self.pci_stats]),
                         set(['v1', 'v2']))
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set([1, 2]))

    def test_remove_device(self):
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertEqual(len(self.pci_stats.pools), 1)
        self.assertEqual(self.pci_stats.pools[0]['count'], 2)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')

    def test_remove_device_exception(self):
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertRaises(exception.PciDevicePoolEmpty,
                          self.pci_stats.remove_device,
                          self.fake_dev_2)

    def test_json_creat(self):
        m = jsonutils.dumps(self.pci_stats)
        new_stats = stats.PciDeviceStats(m)

        self.assertEqual(len(new_stats.pools), 2)
        self.assertEqual(set([d['count'] for d in new_stats]),
                         set([1, 2]))
        self.assertEqual(set([d['vendor_id'] for d in new_stats]),
                         set(['v1', 'v2']))

    def test_support_requests(self):
        self.assertEqual(self.pci_stats.support_requests(pci_requests),
                         True)
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set((1, 2)))

    def test_support_requests_failed(self):
        self.assertEqual(
            self.pci_stats.support_requests(pci_requests_multiple), False)
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set([1, 2]))

    def test_apply_requests(self):
        self.pci_stats.apply_requests(pci_requests)
        self.assertEqual(len(self.pci_stats.pools), 1)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')
        self.assertEqual(self.pci_stats.pools[0]['count'], 1)

    def test_apply_requests_failed(self):
        self.assertRaises(exception.PciDeviceRequestFailed,
            self.pci_stats.apply_requests,
            pci_requests_multiple)

    def test_consume_requests(self):
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['v1', 'v2']),
                         set([dev['vendor_id'] for dev in devs]))

    def test_consume_requests_empty(self):
        devs = self.pci_stats.consume_requests([])
        self.assertEqual(0, len(devs))

    def test_consume_requests_failed(self):
        self.assertRaises(exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests_multiple)


@mock.patch.object(whitelist, 'get_pci_devices_filter')
class PciDeviceStatsWithTagsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PciDeviceStatsWithTagsTestCase, self).setUp()
        self.pci_stats = stats.PciDeviceStats()
        self._create_whitelist()

    def _create_whitelist(self):
        white_list = ['{"vendor_id":"1137","product_id":"0071",'
                        '"address":"*:0a:00.*","physical_network":"physnet1"}',
                       '{"vendor_id":"1137","product_id":"0072"}']
        self.pci_wlist = whitelist.PciHostDevicesWhiteList(white_list)

    def _create_pci_devices(self):
        self.pci_tagged_devices = []
        for dev in range(4):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:0a:00.%d' % dev,
                       'vendor_id': '1137',
                       'product_id': '0071',
                       'status': 'available',
                       'request_id': None}
            self.pci_tagged_devices.append(objects.PciDevice.create(pci_dev))

        self.pci_untagged_devices = []
        for dev in range(3):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:0b:00.%d' % dev,
                       'vendor_id': '1137',
                       'product_id': '0072',
                       'status': 'available',
                       'request_id': None}
            self.pci_untagged_devices.append(objects.PciDevice.create(pci_dev))

        map(self.pci_stats.add_device, self.pci_tagged_devices)
        map(self.pci_stats.add_device, self.pci_untagged_devices)

    def _assertPoolContent(self, pool, vendor_id, product_id, count, **tags):
        self.assertEqual(vendor_id, pool['vendor_id'])
        self.assertEqual(product_id, pool['product_id'])
        self.assertEqual(count, pool['count'])
        if tags:
            for k, v in tags.iteritems():
                self.assertEqual(v, pool[k])

    def _assertPools(self):
        # Pools are ordered based on the number of keys. 'product_id',
        # 'vendor_id' are always part of the keys. When tags are present,
        # they are also part of the keys. In this test class, we have
        # two pools with the second one having the tag 'physical_network'
        # and the value 'physnet1'
        self.assertEqual(2, len(self.pci_stats.pools))
        self._assertPoolContent(self.pci_stats.pools[0], '1137', '0072',
                                len(self.pci_untagged_devices))
        self.assertEqual(self.pci_untagged_devices,
                         self.pci_stats.pools[0]['devices'])
        self._assertPoolContent(self.pci_stats.pools[1], '1137', '0071',
                                len(self.pci_tagged_devices),
                                physical_network='physnet1')
        self.assertEqual(self.pci_tagged_devices,
                         self.pci_stats.pools[1]['devices'])

    def test_add_devices(self, mock_get_dev_filter):
        mock_get_dev_filter.return_value = self.pci_wlist
        self._create_pci_devices()
        self._assertPools()

    def test_consume_reqeusts(self, mock_get_dev_filter):
        mock_get_dev_filter.return_value = self.pci_wlist
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=1,
                            spec=[{'physical_network': 'physnet1'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '1137',
                                   'product_id': '0072'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['0071', '0072']),
                         set([dev['product_id'] for dev in devs]))
        self._assertPoolContent(self.pci_stats.pools[0], '1137', '0072', 2)
        self._assertPoolContent(self.pci_stats.pools[1], '1137', '0071', 3,
                                physical_network='physnet1')

    def test_add_device_no_devspec(self, mock_get_dev_filter):
        mock_get_dev_filter.return_value = self.pci_wlist
        self._create_pci_devices()
        pci_dev = {'compute_node_id': 1,
                   'address': '0000:0c:00.1',
                   'vendor_id': '2345',
                   'product_id': '0172',
                   'status': 'available',
                   'request_id': None}
        pci_dev_obj = objects.PciDevice.create(pci_dev)
        self.pci_stats.add_device(pci_dev_obj)
        # There should be no change
        self.assertIsNone(
            self.pci_stats._create_pool_keys_from_dev(pci_dev_obj))
        self._assertPools()

    def test_remove_device_no_devspec(self, mock_get_dev_filter):
        mock_get_dev_filter.return_value = self.pci_wlist
        self._create_pci_devices()
        pci_dev = {'compute_node_id': 1,
                   'address': '0000:0c:00.1',
                   'vendor_id': '2345',
                   'product_id': '0172',
                   'status': 'available',
                   'request_id': None}
        pci_dev_obj = objects.PciDevice.create(pci_dev)
        self.pci_stats.remove_device(pci_dev_obj)
        # There should be no change
        self.assertIsNone(
            self.pci_stats._create_pool_keys_from_dev(pci_dev_obj))
        self._assertPools()

    def test_remove_device(self, mock_get_dev_filter):
        mock_get_dev_filter.return_value = self.pci_wlist
        self._create_pci_devices()
        dev1 = self.pci_untagged_devices.pop()
        self.pci_stats.remove_device(dev1)
        dev2 = self.pci_tagged_devices.pop()
        self.pci_stats.remove_device(dev2)
        self._assertPools()
