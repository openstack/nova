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
from nova.openstack.common import jsonutils
from nova.pci import pci_stats as pci
from nova import test

fake_pci_1 = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p1',
    'vendor_id': 'v1',
    'status': 'available',
    'extra_k1': 'v1',
    }


fake_pci_2 = dict(fake_pci_1, vendor_id='v2',
                  product_id='p2',
                  address='0000:00:00.2')


fake_pci_3 = dict(fake_pci_1, address='0000:00:00.3')


pci_requests = [{'count': 1,
                 'spec': [{'vendor_id': 'v1'}]},
                {'count': 1,
                 'spec': [{'vendor_id': 'v2'}]}]


pci_requests_multiple = [{'count': 1,
                          'spec': [{'vendor_id': 'v1'}]},
                         {'count': 3,
                          'spec': [{'vendor_id': 'v2'}]}]


class PciDeviceStatsTestCase(test.NoDBTestCase):
    def _create_fake_devs(self):
        self.fake_dev_1 = pci_device.PciDevice.create(fake_pci_1)
        self.fake_dev_2 = pci_device.PciDevice.create(fake_pci_2)
        self.fake_dev_3 = pci_device.PciDevice.create(fake_pci_3)

        map(self.pci_stats.add_device,
            [self.fake_dev_1, self.fake_dev_2, self.fake_dev_3])

    def setUp(self):
        super(PciDeviceStatsTestCase, self).setUp()
        self.pci_stats = pci.PciDeviceStats()
        self._create_fake_devs()

    def test_add_device(self):
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(set([d['vendor_id'] for d in self.pci_stats]),
                         set(['v1', 'v2']))
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set([1, 2]))

    def test_remove_device(self):
        self.pci_stats.consume_device(self.fake_dev_2)
        self.assertEqual(len(self.pci_stats.pools), 1)
        self.assertEqual(self.pci_stats.pools[0]['count'], 2)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')

    def test_remove_device_exception(self):
        self.pci_stats.consume_device(self.fake_dev_2)
        self.assertRaises(exception.PciDevicePoolEmpty,
                          self.pci_stats.consume_device,
                          self.fake_dev_2)

    def test_json_creat(self):
        m = jsonutils.dumps(self.pci_stats)
        new_stats = pci.PciDeviceStats(m)

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
