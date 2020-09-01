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
from oslo_config import cfg

from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci import stats
from nova.pci import whitelist
from nova import test
from nova.tests.unit.pci import fakes

CONF = cfg.CONF
fake_pci_1 = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p1',
    'vendor_id': 'v1',
    'status': 'available',
    'extra_k1': 'v1',
    'request_id': None,
    'numa_node': 0,
    'dev_type': fields.PciDeviceType.STANDARD,
    'parent_addr': None,
    }


fake_pci_2 = dict(fake_pci_1, vendor_id='v2',
                  product_id='p2',
                  address='0000:00:00.2',
                  numa_node=1)


fake_pci_3 = dict(fake_pci_1, address='0000:00:00.3')

fake_pci_4 = dict(fake_pci_1, vendor_id='v3',
                  product_id='p3',
                  address='0000:00:00.3',
                  numa_node= None)

pci_requests = [objects.InstancePCIRequest(count=1,
                    spec=[{'vendor_id': 'v1'}]),
                objects.InstancePCIRequest(count=1,
                    spec=[{'vendor_id': 'v2'}])]


pci_requests_multiple = [objects.InstancePCIRequest(count=1,
                             spec=[{'vendor_id': 'v1'}]),
                         objects.InstancePCIRequest(count=3,
                          spec=[{'vendor_id': 'v2'}])]


class PciDeviceStatsTestCase(test.NoDBTestCase):

    @staticmethod
    def _get_fake_requests(vendor_ids=None, numa_policy=None, count=1):
        if not vendor_ids:
            vendor_ids = ['v1', 'v2']

        specs = [{'vendor_id': vendor_id} for vendor_id in vendor_ids]

        return [objects.InstancePCIRequest(count=count, spec=[spec],
                numa_policy=numa_policy) for spec in specs]

    def _create_fake_devs(self):
        self.fake_dev_1 = objects.PciDevice.create(None, fake_pci_1)
        self.fake_dev_2 = objects.PciDevice.create(None, fake_pci_2)
        self.fake_dev_3 = objects.PciDevice.create(None, fake_pci_3)
        self.fake_dev_4 = objects.PciDevice.create(None, fake_pci_4)

        for dev in [self.fake_dev_1, self.fake_dev_2,
                    self.fake_dev_3, self.fake_dev_4]:
            self.pci_stats.add_device(dev)

    def _add_fake_devs_with_numa(self):
        fake_pci = dict(fake_pci_1, vendor_id='v4', product_id='pr4')
        devs = [dict(fake_pci, product_id='pr0', numa_node=0, ),
                dict(fake_pci, product_id='pr1', numa_node=1),
                dict(fake_pci, product_id='pr_none', numa_node=None)]

        for dev in devs:
            self.pci_stats.add_device(objects.PciDevice.create(None, dev))

    def setUp(self):
        super(PciDeviceStatsTestCase, self).setUp()
        self.pci_stats = stats.PciDeviceStats()
        # The following two calls need to be made before adding the devices.
        patcher = fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)
        self._create_fake_devs()

    def test_add_device(self):
        self.assertEqual(len(self.pci_stats.pools), 3)
        self.assertEqual(set([d['vendor_id'] for d in self.pci_stats]),
                         set(['v1', 'v2', 'v3']))
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set([1, 2]))

    def test_remove_device(self):
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(self.pci_stats.pools[0]['count'], 2)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')

    def test_remove_device_exception(self):
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertRaises(exception.PciDevicePoolEmpty,
                          self.pci_stats.remove_device,
                          self.fake_dev_2)

    def test_pci_stats_equivalent(self):
        pci_stats2 = stats.PciDeviceStats()
        for dev in [self.fake_dev_1,
                    self.fake_dev_2,
                    self.fake_dev_3,
                    self.fake_dev_4]:
            pci_stats2.add_device(dev)
        self.assertEqual(self.pci_stats, pci_stats2)

    def test_pci_stats_not_equivalent(self):
        pci_stats2 = stats.PciDeviceStats()
        for dev in [self.fake_dev_1,
                    self.fake_dev_2,
                    self.fake_dev_3]:
            pci_stats2.add_device(dev)
        self.assertNotEqual(self.pci_stats, pci_stats2)

    def test_object_create(self):
        m = self.pci_stats.to_device_pools_obj()
        new_stats = stats.PciDeviceStats(m)

        self.assertEqual(len(new_stats.pools), 3)
        self.assertEqual(set([d['count'] for d in new_stats]),
                         set([1, 2]))
        self.assertEqual(set([d['vendor_id'] for d in new_stats]),
                         set(['v1', 'v2', 'v3']))

    def test_apply_requests(self):
        self.pci_stats.apply_requests(pci_requests)
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')
        self.assertEqual(self.pci_stats.pools[0]['count'], 1)

    def test_apply_requests_failed(self):
        self.assertRaises(exception.PciDeviceRequestFailed,
            self.pci_stats.apply_requests,
            pci_requests_multiple)

    def test_support_requests(self):
        self.assertTrue(self.pci_stats.support_requests(pci_requests))
        self.assertEqual(len(self.pci_stats.pools), 3)
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set((1, 2)))

    def test_support_requests_failed(self):
        self.assertFalse(
            self.pci_stats.support_requests(pci_requests_multiple))
        self.assertEqual(len(self.pci_stats.pools), 3)
        self.assertEqual(set([d['count'] for d in self.pci_stats]),
                         set([1, 2]))

    def test_support_requests_numa(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0),
                 objects.InstanceNUMACell(id=1, cpuset=set(), memory=0)]
        self.assertTrue(self.pci_stats.support_requests(pci_requests, cells))

    def test_support_requests_numa_failed(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        self.assertFalse(self.pci_stats.support_requests(pci_requests, cells))

    def test_support_requests_no_numa_info(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        pci_requests = self._get_fake_requests(vendor_ids=['v3'])
        self.assertTrue(self.pci_stats.support_requests(pci_requests, cells))

        # 'legacy' is the default numa_policy so the result must be same
        pci_requests = self._get_fake_requests(vendor_ids=['v3'],
            numa_policy = fields.PCINUMAAffinityPolicy.LEGACY)
        self.assertTrue(self.pci_stats.support_requests(pci_requests, cells))

    def test_support_requests_numa_pci_numa_policy_preferred(self):
        # numa node 0 has 2 devices with vendor_id 'v1'
        # numa node 1 has 1 device with vendor_id 'v2'
        # we request two devices with vendor_id 'v1' and 'v2'.
        # pci_numa_policy is 'preferred' so we can ignore numa affinity
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        pci_requests = self._get_fake_requests(
            numa_policy=fields.PCINUMAAffinityPolicy.PREFERRED)

        self.assertTrue(self.pci_stats.support_requests(pci_requests, cells))

    def test_support_requests_no_numa_info_pci_numa_policy_required(self):
        # pci device with vendor_id 'v3' has numa_node=None.
        # pci_numa_policy is 'required' so we can't use this device
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        pci_requests = self._get_fake_requests(vendor_ids=['v3'],
            numa_policy=fields.PCINUMAAffinityPolicy.REQUIRED)

        self.assertFalse(self.pci_stats.support_requests(pci_requests, cells))

    def test_consume_requests(self):
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['v1', 'v2']),
                         set([dev.vendor_id for dev in devs]))

    def test_consume_requests_empty(self):
        devs = self.pci_stats.consume_requests([])
        self.assertEqual(0, len(devs))

    def test_consume_requests_failed(self):
        self.assertIsNone(self.pci_stats.consume_requests(
                          pci_requests_multiple))

    def test_consume_requests_numa(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0),
                 objects.InstanceNUMACell(id=1, cpuset=set(), memory=0)]
        devs = self.pci_stats.consume_requests(pci_requests, cells)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['v1', 'v2']),
                         set([dev.vendor_id for dev in devs]))

    def test_consume_requests_numa_failed(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        self.assertIsNone(self.pci_stats.consume_requests(pci_requests, cells))

    def test_consume_requests_no_numa_info(self):
        cells = [objects.InstanceNUMACell(id=0, cpuset=set(), memory=0)]
        pci_request = [objects.InstancePCIRequest(count=1,
                    spec=[{'vendor_id': 'v3'}])]
        devs = self.pci_stats.consume_requests(pci_request, cells)
        self.assertEqual(1, len(devs))
        self.assertEqual(set(['v3']),
                         set([dev.vendor_id for dev in devs]))

    def _test_consume_requests_numa_policy(self, cell_ids, policy,
            expected, vendor_id='v4', count=1):
        """Base test for 'consume_requests' function.

        Create three devices with vendor_id of 'v4': 'pr0' in NUMA node 0,
        'pr1' in NUMA node 1, 'pr_none' without NUMA affinity info. Attempt to
        consume a PCI request with a single device with ``vendor_id`` using the
        provided ``cell_ids`` and ``policy``. Compare result against
        ``expected``.
        """
        self._add_fake_devs_with_numa()
        cells = [objects.InstanceNUMACell(id=id, cpuset=set(), memory=0)
                 for id in cell_ids]

        pci_requests = self._get_fake_requests(vendor_ids=[vendor_id],
            numa_policy=policy, count=count)
        devs = self.pci_stats.consume_requests(pci_requests, cells)

        if expected is None:
            self.assertIsNone(devs)
        else:
            self.assertEqual(set(expected),
                             set([dev.product_id for dev in devs]))

    def test_consume_requests_numa_policy_required(self):
        """Ensure REQUIRED policy will ensure NUMA affinity.

        Policy is 'required' which means we must use a device with strict NUMA
        affinity. Request a device from NUMA node 0, which contains such a
        device, and ensure it's used.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.REQUIRED, ['pr0'])

    def test_consume_requests_numa_policy_required_fail(self):
        """Ensure REQUIRED policy will *only* provide NUMA affinity.

        Policy is 'required' which means we must use a device with strict NUMA
        affinity. Request a device from NUMA node 999, which does not contain
        any suitable devices, and ensure nothing is returned.
        """
        self._test_consume_requests_numa_policy(
            [999], fields.PCINUMAAffinityPolicy.REQUIRED, None)

    def test_consume_requests_numa_policy_legacy(self):
        """Ensure LEGACY policy will ensure NUMA affinity if possible.

        Policy is 'legacy' which means we must use a device with strict NUMA
        affinity or no provided NUMA affinity. Request a device from NUMA node
        0, which contains such a device, and ensure it's used.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.LEGACY, ['pr0'])

    def test_consume_requests_numa_policy_legacy_fallback(self):
        """Ensure LEGACY policy will fallback to no NUMA affinity.

        Policy is 'legacy' which means we must use a device with strict NUMA
        affinity or no provided NUMA affinity. Request a device from NUMA node
        999, which contains no such device, and ensure we fallback to the
        device without any NUMA affinity.
        """
        self._test_consume_requests_numa_policy(
            [999], fields.PCINUMAAffinityPolicy.LEGACY, ['pr_none'])

    def test_consume_requests_numa_policy_legacy_multiple(self):
        """Ensure LEGACY policy will use best policy for multiple devices.

        Policy is 'legacy' which means we must use a device with strict NUMA
        affinity or no provided NUMA affinity. Request two devices from NUMA
        node 0, which contains only one such device, and ensure we use that
        device and the next best thing for the second device.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.PREFERRED, ['pr0', 'pr_none'],
            count=2)

    def test_consume_requests_numa_policy_legacy_fail(self):
        """Ensure REQUIRED policy will *not* provide NUMA non-affinity.

        Policy is 'legacy' which means we must use a device with strict NUMA
        affinity or no provided NUMA affinity. Request a device with
        ``vendor_id`` of ``v2``, which can only be found in NUMA node 1, from
        NUMA node 0, and ensure nothing is returned.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.LEGACY, None, vendor_id='v2')

    def test_consume_requests_numa_policy_preferred(self):
        """Ensure PREFERRED policy will ensure NUMA affinity if possible.

        Policy is 'preferred' which means we must use a device with any level
        of NUMA affinity. Request a device from NUMA node 0, which contains
        an affined device, and ensure it's used.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.PREFERRED, ['pr0'])

    def test_consume_requests_numa_policy_preferred_fallback_a(self):
        """Ensure PREFERRED policy will fallback to no NUMA affinity.

        Policy is 'preferred' which means we must use a device with any level
        of NUMA affinity. Request a device from NUMA node 999, which contains
        no such device, and ensure we fallback to the device without any NUMA
        affinity.
        """
        self._test_consume_requests_numa_policy(
            [999], fields.PCINUMAAffinityPolicy.PREFERRED, ['pr_none'])

    def test_consume_requests_numa_policy_preferred_fallback_b(self):
        """Ensure PREFERRED policy will fallback to different NUMA affinity.

        Policy is 'preferred' which means we must use a device with any level
        of NUMA affinity. Request a device with ``vendor_id`` of ``v2``, which
        can only be found in NUMA node 1, from NUMA node 0, and ensure we
        fallback to this device.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.PREFERRED, ['p2'],
            vendor_id='v2')

    def test_consume_requests_numa_policy_preferred_multiple_a(self):
        """Ensure PREFERRED policy will use best policy for multiple devices.

        Policy is 'preferred' which means we must use a device with any level
        of NUMA affinity. Request two devices from NUMA node 0, which contains
        only one such device, and ensure we use that device and gracefully
        degrade for the other device.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.PREFERRED, ['pr0', 'pr_none'],
            count=2)

    def test_consume_requests_numa_policy_preferred_multiple_b(self):
        """Ensure PREFERRED policy will use best policy for multiple devices.

        Policy is 'preferred' which means we must use a device with any level
        of NUMA affinity. Request three devices from NUMA node 0, which
        contains only one such device, and ensure we use that device and
        gracefully degrade for the other devices.
        """
        self._test_consume_requests_numa_policy(
            [0], fields.PCINUMAAffinityPolicy.PREFERRED,
            ['pr0', 'pr_none', 'pr1'], count=3)

    @mock.patch(
        'nova.pci.whitelist.Whitelist._parse_white_list_from_config')
    def test_white_list_parsing(self, mock_whitelist_parse):
        white_list = '{"product_id":"0001", "vendor_id":"8086"}'
        CONF.set_override('passthrough_whitelist', white_list, 'pci')
        pci_stats = stats.PciDeviceStats()
        pci_stats.add_device(self.fake_dev_2)
        pci_stats.remove_device(self.fake_dev_2)
        self.assertEqual(1, mock_whitelist_parse.call_count)


class PciDeviceStatsWithTagsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PciDeviceStatsWithTagsTestCase, self).setUp()
        white_list = ['{"vendor_id":"1137","product_id":"0071",'
                        '"address":"*:0a:00.*","physical_network":"physnet1"}',
                       '{"vendor_id":"1137","product_id":"0072"}']
        self.flags(passthrough_whitelist=white_list, group='pci')
        dev_filter = whitelist.Whitelist(white_list)
        self.pci_stats = stats.PciDeviceStats(dev_filter=dev_filter)

    def _create_pci_devices(self):
        self.pci_tagged_devices = []
        for dev in range(4):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:0a:00.%d' % dev,
                       'vendor_id': '1137',
                       'product_id': '0071',
                       'status': 'available',
                       'request_id': None,
                       'dev_type': 'type-PCI',
                       'parent_addr': None,
                       'numa_node': 0}
            self.pci_tagged_devices.append(objects.PciDevice.create(None,
                                                                    pci_dev))

        self.pci_untagged_devices = []
        for dev in range(3):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:0b:00.%d' % dev,
                       'vendor_id': '1137',
                       'product_id': '0072',
                       'status': 'available',
                       'request_id': None,
                       'dev_type': 'type-PCI',
                       'parent_addr': None,
                       'numa_node': 0}
            self.pci_untagged_devices.append(objects.PciDevice.create(None,
                                                                      pci_dev))

        for dev in self.pci_tagged_devices:
            self.pci_stats.add_device(dev)

        for dev in self.pci_untagged_devices:
            self.pci_stats.add_device(dev)

    def _assertPoolContent(self, pool, vendor_id, product_id, count, **tags):
        self.assertEqual(vendor_id, pool['vendor_id'])
        self.assertEqual(product_id, pool['product_id'])
        self.assertEqual(count, pool['count'])
        if tags:
            for k, v in tags.items():
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

    def test_add_devices(self):
        self._create_pci_devices()
        self._assertPools()

    def test_consume_requests(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=1,
                            spec=[{'physical_network': 'physnet1'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '1137',
                                   'product_id': '0072'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['0071', '0072']),
                         set([dev.product_id for dev in devs]))
        self._assertPoolContent(self.pci_stats.pools[0], '1137', '0072', 2)
        self._assertPoolContent(self.pci_stats.pools[1], '1137', '0071', 3,
                                physical_network='physnet1')

    def test_add_device_no_devspec(self):
        self._create_pci_devices()
        pci_dev = {'compute_node_id': 1,
                   'address': '0000:0c:00.1',
                   'vendor_id': '2345',
                   'product_id': '0172',
                   'status': 'available',
                   'parent_addr': None,
                   'request_id': None}
        pci_dev_obj = objects.PciDevice.create(None, pci_dev)
        self.pci_stats.add_device(pci_dev_obj)
        # There should be no change
        self.assertIsNone(
            self.pci_stats._create_pool_keys_from_dev(pci_dev_obj))
        self._assertPools()

    def test_remove_device_no_devspec(self):
        self._create_pci_devices()
        pci_dev = {'compute_node_id': 1,
                   'address': '0000:0c:00.1',
                   'vendor_id': '2345',
                   'product_id': '0172',
                   'status': 'available',
                   'parent_addr': None,
                   'request_id': None}
        pci_dev_obj = objects.PciDevice.create(None, pci_dev)
        self.pci_stats.remove_device(pci_dev_obj)
        # There should be no change
        self.assertIsNone(
            self.pci_stats._create_pool_keys_from_dev(pci_dev_obj))
        self._assertPools()

    def test_remove_device(self):
        self._create_pci_devices()
        dev1 = self.pci_untagged_devices.pop()
        self.pci_stats.remove_device(dev1)
        dev2 = self.pci_tagged_devices.pop()
        self.pci_stats.remove_device(dev2)
        self._assertPools()

    def test_update_device(self):
        # Update device type of one of the device from type-PCI to
        # type-PF. Verify if the existing pool is updated and a new
        # pool is created with dev_type type-PF.
        self._create_pci_devices()
        dev1 = self.pci_tagged_devices.pop()
        dev1.dev_type = 'type-PF'
        self.pci_stats.update_device(dev1)
        self.assertEqual(3, len(self.pci_stats.pools))
        self._assertPoolContent(self.pci_stats.pools[0], '1137', '0072',
                                len(self.pci_untagged_devices))
        self.assertEqual(self.pci_untagged_devices,
                         self.pci_stats.pools[0]['devices'])
        self._assertPoolContent(self.pci_stats.pools[1], '1137', '0071',
                                len(self.pci_tagged_devices),
                                physical_network='physnet1')
        self.assertEqual(self.pci_tagged_devices,
                         self.pci_stats.pools[1]['devices'])
        self._assertPoolContent(self.pci_stats.pools[2], '1137', '0071',
                                1,
                                physical_network='physnet1')
        self.assertEqual(dev1,
                         self.pci_stats.pools[2]['devices'][0])


class PciDeviceVFPFStatsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PciDeviceVFPFStatsTestCase, self).setUp()
        white_list = ['{"vendor_id":"8086","product_id":"1528"}',
                      '{"vendor_id":"8086","product_id":"1515"}']
        self.flags(passthrough_whitelist=white_list, group='pci')
        self.pci_stats = stats.PciDeviceStats()

    def _create_pci_devices(self, vf_product_id=1515, pf_product_id=1528):
        self.sriov_pf_devices = []
        for dev in range(2):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:81:00.%d' % dev,
                       'vendor_id': '8086',
                       'product_id': '%d' % pf_product_id,
                       'status': 'available',
                       'request_id': None,
                       'dev_type': fields.PciDeviceType.SRIOV_PF,
                       'parent_addr': None,
                       'numa_node': 0}
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.child_devices = []
            self.sriov_pf_devices.append(dev_obj)

        self.sriov_vf_devices = []
        for dev in range(8):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:81:10.%d' % dev,
                       'vendor_id': '8086',
                       'product_id': '%d' % vf_product_id,
                       'status': 'available',
                       'request_id': None,
                       'dev_type': fields.PciDeviceType.SRIOV_VF,
                       'parent_addr': '0000:81:00.%d' % int(dev / 4),
                       'numa_node': 0}
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.parent_device = self.sriov_pf_devices[int(dev / 4)]
            dev_obj.parent_device.child_devices.append(dev_obj)
            self.sriov_vf_devices.append(dev_obj)

        list(map(self.pci_stats.add_device, self.sriov_pf_devices))
        list(map(self.pci_stats.add_device, self.sriov_vf_devices))

    def test_consume_VF_requests(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=2,
                            spec=[{'product_id': '1515'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['1515']),
                            set([dev.product_id for dev in devs]))
        free_devs = self.pci_stats.get_free_devs()
        # Validate that the parents of these VFs has been removed
        # from pools.
        for dev in devs:
            self.assertNotIn(dev.parent_addr,
                             [free_dev.address for free_dev in free_devs])

    def test_consume_PF_requests(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=2,
                            spec=[{'product_id': '1528',
                                    'dev_type': 'type-PF'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['1528']),
                            set([dev.product_id for dev in devs]))
        free_devs = self.pci_stats.get_free_devs()
        # Validate that there are no free devices left, as when allocating
        # both available PFs, its VFs should not be available.
        self.assertEqual(0, len(free_devs))

    def test_consume_VF_and_PF_requests(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=2,
                            spec=[{'product_id': '1515'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '1528',
                                    'dev_type': 'type-PF'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(3, len(devs))
        self.assertEqual(set(['1528', '1515']),
                            set([dev.product_id for dev in devs]))

    def test_consume_VF_and_PF_requests_failed(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=5,
                            spec=[{'product_id': '1515'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '1528',
                                    'dev_type': 'type-PF'}])]
        self.assertIsNone(self.pci_stats.consume_requests(pci_requests))

    def test_consume_VF_and_PF_same_prodict_id_failed(self):
        self._create_pci_devices(pf_product_id=1515)
        pci_requests = [objects.InstancePCIRequest(count=9,
                            spec=[{'product_id': '1515'}])]
        self.assertIsNone(self.pci_stats.consume_requests(pci_requests))
