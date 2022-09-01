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
import collections
from unittest import mock

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci.request import PCI_REMOTE_MANAGED_TAG
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
        self.pci_stats = stats.PciDeviceStats(objects.NUMATopology())
        # The following two calls need to be made before adding the devices.
        patcher = fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)
        self._create_fake_devs()

    def test_add_device(self):
        self.assertEqual(len(self.pci_stats.pools), 4)
        self.assertEqual(set([d['vendor_id'] for d in self.pci_stats]),
                         set(['v1', 'v2', 'v3']))
        self.assertEqual([d['count'] for d in self.pci_stats], [1, 1, 1, 1])

    def test_remove_device(self):
        self.assertEqual(len(self.pci_stats.pools), 4)
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertEqual(len(self.pci_stats.pools), 3)
        self.assertEqual(self.pci_stats.pools[0]['count'], 1)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')
        self.assertEqual(self.pci_stats.pools[1]['count'], 1)
        self.assertEqual(self.pci_stats.pools[1]['vendor_id'], 'v1')

    def test_remove_device_exception(self):
        self.pci_stats.remove_device(self.fake_dev_2)
        self.assertRaises(exception.PciDevicePoolEmpty,
                          self.pci_stats.remove_device,
                          self.fake_dev_2)

    def test_pci_stats_equivalent(self):
        pci_stats2 = stats.PciDeviceStats(objects.NUMATopology())
        for dev in [self.fake_dev_1,
                    self.fake_dev_2,
                    self.fake_dev_3,
                    self.fake_dev_4]:
            pci_stats2.add_device(dev)
        self.assertEqual(self.pci_stats, pci_stats2)

    def test_pci_stats_not_equivalent(self):
        pci_stats2 = stats.PciDeviceStats(objects.NUMATopology())
        for dev in [self.fake_dev_1,
                    self.fake_dev_2,
                    self.fake_dev_3]:
            pci_stats2.add_device(dev)
        self.assertNotEqual(self.pci_stats, pci_stats2)

    def test_object_create(self):
        m = self.pci_stats.to_device_pools_obj()
        new_stats = stats.PciDeviceStats(objects.NUMATopology(), m)

        self.assertEqual(len(new_stats.pools), 4)
        self.assertEqual([d['count'] for d in new_stats], [1, 1, 1, 1])
        self.assertEqual(set([d['vendor_id'] for d in new_stats]),
                         set(['v1', 'v2', 'v3']))

    def test_apply_requests(self):
        self.assertEqual(len(self.pci_stats.pools), 4)
        self.pci_stats.apply_requests(pci_requests, {})
        self.assertEqual(len(self.pci_stats.pools), 2)
        self.assertEqual(self.pci_stats.pools[0]['vendor_id'], 'v1')
        self.assertEqual(self.pci_stats.pools[0]['count'], 1)

    def test_apply_requests_failed(self):
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.apply_requests,
            pci_requests_multiple,
            {},
        )

    def test_support_requests(self):
        self.assertTrue(self.pci_stats.support_requests(pci_requests, {}))
        self.assertEqual(len(self.pci_stats.pools), 4)
        self.assertEqual([d['count'] for d in self.pci_stats], [1, 1, 1, 1])

    def test_support_requests_failed(self):
        self.assertFalse(
            self.pci_stats.support_requests(pci_requests_multiple, {}))
        self.assertEqual(len(self.pci_stats.pools), 4)
        self.assertEqual([d['count'] for d in self.pci_stats], [1, 1, 1, 1])

    def test_support_requests_numa(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
            objects.InstanceNUMACell(
                id=1, cpuset=set(), pcpuset=set(), memory=0),
        ]
        self.assertTrue(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

    def test_support_requests_numa_failed(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
        self.assertFalse(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

    def test_support_requests_no_numa_info(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
        pci_requests = self._get_fake_requests(vendor_ids=['v3'])
        self.assertTrue(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

        # 'legacy' is the default numa_policy so the result must be same
        pci_requests = self._get_fake_requests(vendor_ids=['v3'],
            numa_policy = fields.PCINUMAAffinityPolicy.LEGACY)
        self.assertTrue(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

    def test_support_requests_numa_pci_numa_policy_preferred(self):
        # numa node 0 has 2 devices with vendor_id 'v1'
        # numa node 1 has 1 device with vendor_id 'v2'
        # we request two devices with vendor_id 'v1' and 'v2'.
        # pci_numa_policy is 'preferred' so we can ignore numa affinity
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
        pci_requests = self._get_fake_requests(
            numa_policy=fields.PCINUMAAffinityPolicy.PREFERRED)

        self.assertTrue(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

    def test_support_requests_no_numa_info_pci_numa_policy_required(self):
        # pci device with vendor_id 'v3' has numa_node=None.
        # pci_numa_policy is 'required' so we can't use this device
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
        pci_requests = self._get_fake_requests(vendor_ids=['v3'],
            numa_policy=fields.PCINUMAAffinityPolicy.REQUIRED)

        self.assertFalse(
            self.pci_stats.support_requests(pci_requests, {}, cells)
        )

    def test_filter_pools_for_socket_affinity_no_socket(self):
        self.pci_stats.numa_topology = objects.NUMATopology(
                cells=[objects.NUMACell(socket=None)])

        self.assertEqual(
            [],
            self.pci_stats._filter_pools_for_socket_affinity(
                self.pci_stats.pools, [objects.InstanceNUMACell()]))

    def test_filter_pools_for_socket_affinity(self):
        self.pci_stats.numa_topology = objects.NUMATopology(
                cells=[objects.NUMACell(id=1, socket=1)])

        pools = self.pci_stats._filter_pools_for_socket_affinity(
            self.pci_stats.pools, [objects.InstanceNUMACell(id=1)])
        self.assertEqual(1, len(pools))
        self.assertEqual('p2', pools[0]['product_id'])
        self.assertEqual('v2', pools[0]['vendor_id'])

    def test_consume_requests(self):
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['v1', 'v2']),
                         set([dev.vendor_id for dev in devs]))

    def test_consume_requests_empty(self):
        devs = self.pci_stats.consume_requests([])
        self.assertEqual(0, len(devs))

    def test_consume_requests_failed(self):
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests_multiple,
        )

    def test_consume_requests_numa(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
            objects.InstanceNUMACell(
                id=1, cpuset=set(), pcpuset=set(), memory=0),
        ]
        devs = self.pci_stats.consume_requests(pci_requests, cells)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['v1', 'v2']),
                         set([dev.vendor_id for dev in devs]))

    def test_consume_requests_numa_failed(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests,
            cells,
        )

    def test_consume_requests_no_numa_info(self):
        cells = [
            objects.InstanceNUMACell(
                id=0, cpuset=set(), pcpuset=set(), memory=0),
        ]
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
        cells = [
            objects.InstanceNUMACell(
                id=id, cpuset=set(), pcpuset=set(), memory=0)
            for id in cell_ids]

        pci_requests = self._get_fake_requests(vendor_ids=[vendor_id],
            numa_policy=policy, count=count)

        if expected is None:
            self.assertRaises(
                exception.PciDeviceRequestFailed,
                self.pci_stats.consume_requests,
                pci_requests,
                cells,
            )
        else:
            devs = self.pci_stats.consume_requests(pci_requests, cells)
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
    def test_device_spec_parsing(self, mock_whitelist_parse):
        device_spec = {"product_id": "0001", "vendor_id": "8086"}
        CONF.set_override('device_spec', jsonutils.dumps(device_spec), 'pci')
        pci_stats = stats.PciDeviceStats(objects.NUMATopology())
        pci_stats.add_device(self.fake_dev_2)
        pci_stats.remove_device(self.fake_dev_2)
        self.assertEqual(1, mock_whitelist_parse.call_count)


class PciDeviceStatsWithTagsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PciDeviceStatsWithTagsTestCase, self).setUp()
        device_spec = [
            jsonutils.dumps(
                {
                    "vendor_id": "1137",
                    "product_id": "0071",
                    "address": "*:0a:00.*",
                    "physical_network": "physnet1",
                }
            ),
            jsonutils.dumps({"vendor_id": "1137", "product_id": "0072"}),
            jsonutils.dumps(
                {
                    "vendor_id": "15b3",
                    "product_id": "101e",
                    "remote_managed": "true",
                }
            ),
            jsonutils.dumps({"vendor_id": "15b3", "product_id": "101c"}),
            jsonutils.dumps(
                {
                    "vendor_id": "15b3",
                    "product_id": "1018",
                    "remote_managed": "false",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        dev_filter = whitelist.Whitelist(device_spec)
        self.pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(),
            dev_filter=dev_filter)

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

        self.locally_managed_netdevs = []
        self.remote_managed_netdevs = []
        self.remote_managed_netdevs.append(
            objects.PciDevice.create(
                None, {
                    'compute_node_id': 1,
                    'address': '0000:0c:00.1',
                    'vendor_id': '15b3',
                    'product_id': '101e',
                    'status': 'available',
                    'request_id': None,
                    'dev_type': fields.PciDeviceType.SRIOV_VF,
                    'parent_addr': '0000:0c:00.0',
                    'numa_node': 0,
                    "capabilities": {"vpd": {
                        "card_serial_number": "MT2113X00000"}}
                }))

        # For testing implicit remote_managed == False tagging.
        self.locally_managed_netdevs.append(
            objects.PciDevice.create(
                None, {
                    'compute_node_id': 1,
                    'address': '0000:0d:00.1',
                    'vendor_id': '15b3',
                    'product_id': '101c',
                    'status': 'available',
                    'request_id': None,
                    'dev_type': fields.PciDeviceType.SRIOV_VF,
                    'parent_addr': '0000:0d:00.0',
                    'numa_node': 0}))

        # For testing explicit remote_managed == False tagging.
        self.locally_managed_netdevs.append(
            objects.PciDevice.create(
                None, {
                    'compute_node_id': 1,
                    'address': '0000:0e:00.1',
                    'vendor_id': '15b3',
                    'product_id': '101c',
                    'status': 'available',
                    'request_id': None,
                    'dev_type': fields.PciDeviceType.SRIOV_VF,
                    'parent_addr': '0000:0e:00.0',
                    'numa_node': 0}))

        for dev in self.pci_tagged_devices:
            self.pci_stats.add_device(dev)

        for dev in self.pci_untagged_devices:
            self.pci_stats.add_device(dev)

        for dev in self.remote_managed_netdevs:
            self.pci_stats.add_device(dev)

        for dev in self.locally_managed_netdevs:
            self.pci_stats.add_device(dev)

    def _assertPoolContent(self, pool, vendor_id, product_id, count, **tags):
        self.assertEqual(vendor_id, pool['vendor_id'])
        self.assertEqual(product_id, pool['product_id'])
        self.assertEqual(count, pool['count'])
        if tags:
            for k, v in tags.items():
                self.assertEqual(v, pool[k])

    def _assertPools(self):
        nr_tagged = len(self.pci_tagged_devices)
        nr_untagged = len(self.pci_untagged_devices)
        nr_remote = len(self.remote_managed_netdevs)
        nr_local = len(self.locally_managed_netdevs)
        self.assertEqual(
            nr_tagged + nr_untagged + nr_remote + nr_local,
            len(self.pci_stats.pools),
        )
        # Pools are ordered based on the number of keys. 'product_id',
        # 'vendor_id' are always part of the keys. When tags are present,
        # they are also part of the keys.

        # 3 pools for the pci_untagged_devices
        devs = []
        j = 0
        for i in range(j, j + nr_untagged):
            self._assertPoolContent(self.pci_stats.pools[i], '1137', '0072', 1)
            devs += self.pci_stats.pools[i]['devices']
        self.assertEqual(self.pci_untagged_devices, devs)
        j += nr_untagged

        # 4 pools for the pci_tagged_devices'
        devs = []
        for i in range(j, j + nr_tagged):
            self._assertPoolContent(
                self.pci_stats.pools[i],
                "1137",
                "0071",
                1,
                physical_network="physnet1",
            )
            devs += self.pci_stats.pools[i]['devices']
        self.assertEqual(self.pci_tagged_devices, devs)
        j += nr_tagged

        # one with remote_managed_netdevs
        devs = []
        for i in range(j, j + nr_remote):
            self._assertPoolContent(
                self.pci_stats.pools[i],
                "15b3",
                "101e",
                1,
                remote_managed="true",
            )
            devs += self.pci_stats.pools[i]['devices']
        self.assertEqual(self.remote_managed_netdevs, devs)
        j += nr_remote

        # two with locally_managed_netdevs
        devs = []
        for i in range(j, j + nr_local):
            self._assertPoolContent(
                self.pci_stats.pools[i],
                "15b3",
                "101c",
                1,
                remote_managed="false",
            )
            devs += self.pci_stats.pools[i]['devices']
        self.assertEqual(self.locally_managed_netdevs, devs)
        j += nr_local

    def test_add_devices(self):
        self._create_pci_devices()
        self._assertPools()

    def test_consume_requests(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=1,
                            spec=[{'physical_network': 'physnet1'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '1137',
                                   'product_id': '0072'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '15b3',
                                   'product_id': '101e',
                                   PCI_REMOTE_MANAGED_TAG: 'True'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '15b3',
                                   'product_id': '101c',
                                   PCI_REMOTE_MANAGED_TAG: 'False'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'vendor_id': '15b3',
                                   'product_id': '101c',
                                   PCI_REMOTE_MANAGED_TAG: 'False'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(5, len(devs))
        self.assertEqual(set(['0071', '0072', '101e', '101c']),
                         set([dev.product_id for dev in devs]))
        self._assertPoolContent(self.pci_stats.pools[0], '1137', '0072', 0)
        self._assertPoolContent(self.pci_stats.pools[1], '1137', '0072', 1)
        self._assertPoolContent(self.pci_stats.pools[2], '1137', '0072', 1)

        self._assertPoolContent(self.pci_stats.pools[3], '1137', '0071', 0,
                                physical_network='physnet1')
        self._assertPoolContent(self.pci_stats.pools[4], '1137', '0071', 1,
                                physical_network='physnet1')
        self._assertPoolContent(self.pci_stats.pools[5], '1137', '0071', 1,
                                physical_network='physnet1')
        self._assertPoolContent(self.pci_stats.pools[6], '1137', '0071', 1,
                                physical_network='physnet1')

        self._assertPoolContent(self.pci_stats.pools[7], '15b3', '101e', 0,
                                remote_managed='true')
        self._assertPoolContent(self.pci_stats.pools[8], '15b3', '101c', 0,
                                remote_managed='false')
        self._assertPoolContent(self.pci_stats.pools[9], '15b3', '101c', 0,
                                remote_managed='false')

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

    def test_update_device_splits_the_pool(self):
        # Update device type of one of the device from type-VF to
        # type-PF. Verify if the existing pool is updated and a new
        # pool is created with dev_type type-PF.
        vfs = []
        for i in range(3):
            dev = objects.PciDevice(
                    compute_node_id=1,
                    address="0000:0a:00.%d" % i,
                    vendor_id="1137",
                    product_id="0071",
                    status="available",
                    dev_type="type-VF",
                    parent_addr="0000:0a:01.0",
                    numa_node=0
                )
            vfs.append(dev)
            self.pci_stats.add_device(dev)

        self.assertEqual(1, len(self.pci_stats.pools))
        self.assertEqual(3, self.pci_stats.pools[0]["count"])
        self.assertEqual(vfs, self.pci_stats.pools[0]["devices"])

        dev = vfs.pop()
        dev.dev_type = 'type-PF'
        dev.parent_addr = None
        self.pci_stats.update_device(dev)
        self.assertEqual(2, len(self.pci_stats.pools))
        self.assertEqual(2, self.pci_stats.pools[0]["count"])
        self.assertEqual(vfs, self.pci_stats.pools[0]["devices"])
        self.assertEqual(1, self.pci_stats.pools[1]["count"])
        self.assertEqual([dev], self.pci_stats.pools[1]["devices"])

    def test_only_vfs_from_the_same_parent_are_pooled(self):
        pf1_vfs = []
        for i in range(2):
            dev = objects.PciDevice(
                    compute_node_id=1,
                    address="0000:0a:00.%d" % i,
                    vendor_id="15b3",
                    product_id="1018",
                    status="available",
                    dev_type="type-VF",
                    parent_addr="0000:0a:01.0",
                    numa_node=0
                )
            pf1_vfs.append(dev)
            self.pci_stats.add_device(dev)

        pf2_vfs = []
        for i in range(2):
            dev = objects.PciDevice(
                    compute_node_id=1,
                    address="0000:0b:00.%d" % i,
                    vendor_id="15b3",
                    product_id="1018",
                    status="available",
                    dev_type="type-VF",
                    parent_addr="0000:0b:01.0",
                    numa_node=0
                )
            pf2_vfs.append(dev)
            self.pci_stats.add_device(dev)

        self.assertEqual(2, len(self.pci_stats.pools))
        self.assertEqual(2, self.pci_stats.pools[0]["count"])
        self.assertEqual(pf1_vfs, self.pci_stats.pools[0]["devices"])
        self.assertEqual(2, len(self.pci_stats.pools))
        self.assertEqual(2, self.pci_stats.pools[1]["count"])
        self.assertEqual(pf2_vfs, self.pci_stats.pools[1]["devices"])


class PciDeviceStatsPlacementSupportTestCase(test.NoDBTestCase):

    def test_device_spec_rc_and_traits_ignored_during_pooling(self):
        """Assert that resource_class and traits from the device spec are not
        used as discriminator for pool creation.
        """
        device_spec = [
            jsonutils.dumps(
                {
                    "resource_class": "foo",
                    "address": "*:81:00.1",
                    "traits": "gold",
                }
            ),
            jsonutils.dumps(
                {
                    "resource_class": "baar",
                    "address": "*:81:00.2",
                    "traits": "silver",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        dev_filter = whitelist.Whitelist(device_spec)
        pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(),
            dev_filter=dev_filter)
        pci_dev1 = objects.PciDevice(
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.1",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_dev2 = objects.PciDevice(
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.2",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        # the two device matched by different device_specs with different
        # resource_class and traits fields
        pci_stats.add_device(pci_dev1)
        pci_stats.add_device(pci_dev2)

        # but they are put in the same pool as all the other fields are
        # matching
        self.assertEqual(1, len(pci_stats.pools))
        self.assertEqual(2, pci_stats.pools[0]["count"])

    def test_filter_pools_for_spec_ignores_rc_and_traits_in_spec(self):
        """Assert that resource_class and traits are ignored in the pci
        request spec during matching the request to pools.
        """
        pci_stats = stats.PciDeviceStats(objects.NUMATopology())
        pools = [{"vendor_id": "dead", "product_id": "beef"}]

        matching_pools = pci_stats._filter_pools_for_spec(
            pools=pools,
            request=objects.InstancePCIRequest(
                spec=[
                    {
                        "vendor_id": "dead",
                        "product_id": "beef",
                        "resource_class": "foo",
                        "traits": "blue",
                    }
                ]
            ),
        )

        self.assertEqual(pools, matching_pools)

    def test_populate_pools_metadata_from_assigned_devices(self):
        device_spec = [
            jsonutils.dumps(
                {
                    "address": "0000:81:00.*",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        dev_filter = whitelist.Whitelist(device_spec)
        pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(),
            dev_filter=dev_filter)
        pci_dev1 = objects.PciDevice(
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.1",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_dev2 = objects.PciDevice(
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.2",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_stats.add_device(pci_dev1)
        pci_dev1.extra_info = {'rp_uuid': uuids.rp1}
        pci_stats.add_device(pci_dev2)
        pci_dev2.extra_info = {'rp_uuid': uuids.rp1}

        self.assertEqual(1, len(pci_stats.pools))

        pci_stats.populate_pools_metadata_from_assigned_devices()

        self.assertEqual(uuids.rp1, pci_stats.pools[0]['rp_uuid'])

    def test_populate_pools_metadata_from_assigned_devices_device_without_rp(
        self
    ):
        device_spec = [
            jsonutils.dumps(
                {
                    "address": "0000:81:00.*",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        dev_filter = whitelist.Whitelist(device_spec)
        pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(),
            dev_filter=dev_filter)
        pci_dev1 = objects.PciDevice(
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.1",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_stats.add_device(pci_dev1)

        self.assertEqual(1, len(pci_stats.pools))

        pci_stats.populate_pools_metadata_from_assigned_devices()

        self.assertNotIn('rp_uuid', pci_stats.pools[0])

    def test_populate_pools_metadata_from_assigned_devices_multiple_rp(self):
        device_spec = [
            jsonutils.dumps(
                {
                    "address": "0000:81:00.*",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        dev_filter = whitelist.Whitelist(device_spec)
        pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(),
            dev_filter=dev_filter)
        pci_dev1 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.1",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_dev2 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.2",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        pci_stats.add_device(pci_dev1)
        pci_dev1.extra_info = {'rp_uuid': uuids.rp1}
        pci_stats.add_device(pci_dev2)
        pci_dev2.extra_info = {'rp_uuid': uuids.rp2}

        self.assertEqual(1, len(pci_stats.pools))

        self.assertRaises(
            ValueError,
            pci_stats.populate_pools_metadata_from_assigned_devices,
        )


class PciDeviceStatsProviderMappingTestCase(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        # for simplicity accept any devices
        device_spec = [
            jsonutils.dumps(
                {
                    "address": "*:*:*.*",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group="pci")
        self.dev_filter = whitelist.Whitelist(device_spec)
        self.pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(), dev_filter=self.dev_filter
        )
        # add devices represented by different RPs in placement
        # two VFs on the same PF
        self.vf1 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.1",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        self.vf2 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:81:00.2",
            parent_addr="0000:81:00.0",
            numa_node=0,
            dev_type="type-VF",
        )
        self.pci_stats.add_device(self.vf1)
        self.vf1.extra_info = {'rp_uuid': uuids.pf1}
        self.pci_stats.add_device(self.vf2)
        self.vf2.extra_info = {'rp_uuid': uuids.pf1}
        # two PFs pf2 and pf3 (pf1 is used for the paren of the above VFs)
        self.pf2 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:82:00.0",
            parent_addr=None,
            numa_node=0,
            dev_type="type-PF",
        )
        self.pci_stats.add_device(self.pf2)
        self.pf2.extra_info = {'rp_uuid': uuids.pf2}

        self.pf3 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:83:00.0",
            parent_addr=None,
            numa_node=0,
            dev_type="type-PF",
        )
        self.pci_stats.add_device(self.pf3)
        self.pf3.extra_info = {'rp_uuid': uuids.pf3}
        # a PCI
        self.pci1 = objects.PciDevice(
            compute_node_id=1,
            vendor_id="dead",
            product_id="beef",
            address="0000:84:00.0",
            parent_addr=None,
            numa_node=0,
            dev_type="type-PCI",
        )
        self.pci_stats.add_device(self.pci1)
        self.pci1.extra_info = {'rp_uuid': uuids.pci1}

        # populate the RP -> pool mapping from the devices to its pools
        self.pci_stats.populate_pools_metadata_from_assigned_devices()

        # we have 1 pool for the two VFs then the rest has it own pool one by
        # one
        self.num_pools = 4
        self.assertEqual(self.num_pools, len(self.pci_stats.pools))
        self.num_devs = 5
        self.assertEqual(
            self.num_devs, sum(pool["count"] for pool in self.pci_stats.pools)
        )

    def test_support_request_unrestricted(self):
        reqs = []
        for dev_type in ["type-VF", "type-PF", "type-PCI"]:
            req = objects.InstancePCIRequest(
                count=1,
                alias_name='a-dev',
                spec=[
                    {
                        "vendor_id": "dead",
                        "product_id": "beef",
                        "dev_type": dev_type,
                    }
                ],
            )
            reqs.append(req)

        # an empty mapping means unrestricted by any provider
        # we have devs for all type so each request should fit
        self.assertTrue(self.pci_stats.support_requests(reqs, {}))

        # the support_requests call is expected not to consume any device
        self.assertEqual(self.num_pools, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs, sum(pool["count"] for pool in self.pci_stats.pools)
        )

        # now apply the same request to consume the pools
        self.pci_stats.apply_requests(reqs, {})
        # we have consumed a 3 devs (a VF, a PF, and a PCI)
        self.assertEqual(
            self.num_devs - 3,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )
        # the empty pools are purged. We have one pool for the remaining VF
        # and the remaining PF
        self.assertEqual(2, len(self.pci_stats.pools))

    def test_support_request_restricted_by_provider_mapping(self):
        pf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                }
            ],
        )

        # simulate the placement restricted the possible RPs to pf3
        self.assertTrue(
            self.pci_stats.support_requests(
                [pf_req], {f"{uuids.req1}-0": [uuids.pf3]}
            )
        )

        # the support_requests call is expected not to consume any device
        self.assertEqual(self.num_pools, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs, sum(pool["count"] for pool in self.pci_stats.pools)
        )

        # now apply the request and see if the right device is consumed
        self.pci_stats.apply_requests(
            [pf_req], {f"{uuids.req1}-0": [uuids.pf3]}
        )

        self.assertEqual(self.num_pools - 1, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs - 1,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )
        # pf3 is not available in the pools any more
        self.assertEqual(
            {uuids.pf1, uuids.pf2, uuids.pci1},
            {pool['rp_uuid'] for pool in self.pci_stats.pools},
        )

    def test_support_request_restricted_by_provider_mapping_does_not_fit(self):
        pf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                }
            ],
        )

        # Simulate that placement returned an allocation candidate with a PF
        # that is not in the pools anymore, e.g. filtered out by numa cell.
        # We expect the request to fail
        self.assertFalse(
            self.pci_stats.support_requests(
                [pf_req], {f"{uuids.req1}-0": [uuids.pf4]}
            )
        )
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.apply_requests,
            [pf_req],
            {f"{uuids.req1}-0": [uuids.pf4]},
        )
        # and the pools are not changed
        self.assertEqual(self.num_pools, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs, sum(pool["count"] for pool in self.pci_stats.pools)
        )

    def test_support_request_neutron_port_based_request_ignore_mapping(self):
        # by not having the alias_name set this becomes a neutron port based
        # PCI request
        pf_req = objects.InstancePCIRequest(
            count=1,
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                }
            ],
        )

        # Simulate that placement returned an allocation candidate with a PF
        # that is not in the pools anymore, e.g. filtered out by numa cell.
        # We expect that the placement selection is ignored for neutron port
        # based requests so this request should fit as we have PFs in the pools
        self.assertTrue(
            self.pci_stats.support_requests(
                [pf_req], {f"{uuids.req1}-0": [uuids.pf4]}
            )
        )
        self.pci_stats.apply_requests(
            [pf_req],
            {f"{uuids.req1}-0": [uuids.pf4]},
        )
        # and a PF is consumed
        self.assertEqual(self.num_pools - 1, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs - 1,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )

    def test_support_request_req_with_count_2(self):
        # now ask for two PFs in a single request
        pf_req = objects.InstancePCIRequest(
            count=2,
            alias_name='a-dev',
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                }
            ],
        )

        # Simulate that placement returned one candidate RP for both PF reqs
        mapping = {
            f"{uuids.req1}-0": [uuids.pf2],
            f"{uuids.req1}-1": [uuids.pf3],
        }
        # so the request fits
        self.assertTrue(self.pci_stats.support_requests([pf_req], mapping))
        self.pci_stats.apply_requests([pf_req], mapping)
        # and both PFs are consumed
        self.assertEqual(self.num_pools - 2, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs - 2,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )
        self.assertEqual(
            {uuids.pf1, uuids.pci1},
            {pool['rp_uuid'] for pool in self.pci_stats.pools},
        )

    def test_support_requests_multiple_reqs(self):
        # request both a VF and a PF
        vf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.vf_req,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-VF",
                }
            ],
        )
        pf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.pf_req,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                }
            ],
        )

        # Simulate that placement returned one candidate RP for both reqs
        mapping = {
            # the VF is represented by the parent PF RP
            f"{uuids.vf_req}-0": [uuids.pf1],
            f"{uuids.pf_req}-0": [uuids.pf3],
        }
        # so the request fits
        self.assertTrue(
            self.pci_stats.support_requests([vf_req, pf_req], mapping)
        )
        self.pci_stats.apply_requests([vf_req, pf_req], mapping)
        # and the proper devices are consumed
        # Note that the VF pool still has a device so it remains
        self.assertEqual(self.num_pools - 1, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs - 2,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )
        self.assertEqual(
            {uuids.pf1, uuids.pf2, uuids.pci1},
            {pool['rp_uuid'] for pool in self.pci_stats.pools},
        )

    def test_apply_gets_requested_uuids_from_pci_req(self):
        pf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                    # Simulate that the scheduler already allocate a candidate
                    # and the mapping is stored in the request.
                    # The allocation restricts that we can only consume from
                    # PF3
                    "rp_uuids": ",".join([uuids.pf3])
                }
            ],
        )

        # call apply with None mapping signalling that the allocation is
        # already done and the resulted mapping is stored in the request
        self.pci_stats.apply_requests([pf_req], provider_mapping=None)

        # assert that the right device is consumed
        self.assertEqual(self.num_pools - 1, len(self.pci_stats.pools))
        self.assertEqual(
            self.num_devs - 1,
            sum(pool["count"] for pool in self.pci_stats.pools),
        )
        # pf3 is not available in the pools anymore
        self.assertEqual(
            {uuids.pf1, uuids.pf2, uuids.pci1},
            {pool['rp_uuid'] for pool in self.pci_stats.pools},
        )

    def _create_two_pools_with_two_vfs(self):
        # create two pools (PFs) with two VFs each
        self.pci_stats = stats.PciDeviceStats(
            objects.NUMATopology(), dev_filter=self.dev_filter
        )
        for pf_index in [1, 2]:
            for vf_index in [1, 2]:
                dev = objects.PciDevice(
                    compute_node_id=1,
                    vendor_id="dead",
                    product_id="beef",
                    address=f"0000:81:0{pf_index}.{vf_index}",
                    parent_addr=f"0000:81:0{pf_index}.0",
                    numa_node=0,
                    dev_type="type-VF",
                )
                self.pci_stats.add_device(dev)
                dev.extra_info = {'rp_uuid': getattr(uuids, f"pf{pf_index}")}

        # populate the RP -> pool mapping from the devices to its pools
        self.pci_stats.populate_pools_metadata_from_assigned_devices()

        # we have 2 pool and 4 devs in total
        self.num_pools = 2
        self.assertEqual(self.num_pools, len(self.pci_stats.pools))
        self.num_devs = 4
        self.assertEqual(
            self.num_devs, sum(pool["count"] for pool in self.pci_stats.pools)
        )

    def test_apply_asymmetric_allocation(self):
        self._create_two_pools_with_two_vfs()
        # ask for 3 VFs
        vf_req = objects.InstancePCIRequest(
            count=3,
            alias_name='a-vf',
            request_id=uuids.vf_req,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-VF",
                }
            ],
        )

        # Simulate that placement returned an allocation candidate where 1 VF
        # is consumed from PF1 and two from PF2
        mapping = {
            # the VF is represented by the parent PF RP
            f"{uuids.vf_req}-0": [uuids.pf1],
            f"{uuids.vf_req}-1": [uuids.pf2],
            f"{uuids.vf_req}-2": [uuids.pf2],
        }
        # This should fit
        self.assertTrue(
            self.pci_stats.support_requests([vf_req], mapping)
        )
        # and when consumed the consumption from the pools should be in sync
        # with the placement allocation. So the PF2 pool is expected to
        # disappear as it is fully consumed and the PF1 pool should have
        # one free device.
        self.pci_stats.apply_requests([vf_req], mapping)
        self.assertEqual(1, len(self.pci_stats.pools))
        self.assertEqual(uuids.pf1, self.pci_stats.pools[0]['rp_uuid'])
        self.assertEqual(1, self.pci_stats.pools[0]['count'])

    def test_consume_asymmetric_allocation(self):
        self._create_two_pools_with_two_vfs()
        # ask for 3 VFs
        vf_req = objects.InstancePCIRequest(
            count=3,
            alias_name='a-vf',
            request_id=uuids.vf_req,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-VF",
                    # Simulate that the scheduler already allocate a candidate
                    # and the mapping is stored in the request.
                    # In placement 1 VF is allocated from PF1 and two from PF2
                    "rp_uuids": ",".join([uuids.pf1, uuids.pf2, uuids.pf2])
                }
            ],
        )

        # So when the PCI claim consumes devices based on this request we
        # expect that nova follows what is allocated in placement.
        devs = self.pci_stats.consume_requests([vf_req])
        self.assertEqual(
            {"0000:81:01.0": 1, "0000:81:02.0": 2},
            collections.Counter(dev.parent_addr for dev in devs),
        )

    def test_consume_restricted_by_allocation(self):
        pf_req = objects.InstancePCIRequest(
            count=1,
            alias_name='a-dev',
            request_id=uuids.req1,
            spec=[
                {
                    "vendor_id": "dead",
                    "product_id": "beef",
                    "dev_type": "type-PF",
                    # Simulate that the scheduler already allocate a candidate
                    # and the mapping is stored in the request.
                    # The allocation restricts that we can only consume from
                    # PF3
                    "rp_uuids": ",".join([uuids.pf3])
                }
            ],
        )

        # Call consume. It always expects the allocated mapping to be stores
        # the in PCI request as it is always called from the compute side.
        consumed_devs = self.pci_stats.consume_requests([pf_req])
        # assert that the right device is consumed
        self.assertEqual([self.pf3], consumed_devs)
        # pf3 is not available in the pools anymore
        self.assertEqual(
            {uuids.pf1, uuids.pf2, uuids.pci1},
            {
                pool["rp_uuid"]
                for pool in self.pci_stats.pools
                if pool["count"] > 0
            },
        )


class PciDeviceVFPFStatsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PciDeviceVFPFStatsTestCase, self).setUp()
        device_spec = [
            jsonutils.dumps({"vendor_id": "8086", "product_id": "1528"}),
            jsonutils.dumps({"vendor_id": "8086", "product_id": "1515"}),
            jsonutils.dumps(
                {
                    "vendor_id": "15b3",
                    "product_id": "a2d6",
                    "remote_managed": "false",
                }
            ),
            jsonutils.dumps(
                {
                    "vendor_id": "15b3",
                    "product_id": "101e",
                    "remote_managed": "true",
                }
            ),
        ]
        self.flags(device_spec=device_spec, group='pci')
        self.pci_stats = stats.PciDeviceStats(objects.NUMATopology())

    def _create_pci_devices(self, vf_product_id=1515, pf_product_id=1528):
        self.sriov_pf_devices = []
        for dev in range(2):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:81:00.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % pf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_PF,
                'parent_addr': None,
                'numa_node': 0
            }
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.child_devices = []
            self.sriov_pf_devices.append(dev_obj)

        # PF devices for remote_managed VFs.
        self.sriov_pf_devices_remote = []
        for dev in range(2):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0001:81:00.%d' % dev,
                'vendor_id': '15b3',
                'product_id': 'a2d6',
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_PF,
                'parent_addr': None,
                'numa_node': 0,
                "capabilities": {"vpd": {
                    "card_serial_number": "MT2113X00000"}},
            }
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.child_devices = []
            self.sriov_pf_devices_remote.append(dev_obj)

        self.sriov_vf_devices = []
        for dev in range(8):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:81:10.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % vf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'parent_addr': '0000:81:00.%d' % int(dev / 4),
                'numa_node': 0
            }
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.parent_device = self.sriov_pf_devices[int(dev / 4)]
            dev_obj.parent_device.child_devices.append(dev_obj)
            self.sriov_vf_devices.append(dev_obj)

        self.sriov_vf_devices_remote = []
        for dev in range(8):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0001:81:10.%d' % dev,
                'vendor_id': '15b3',
                'product_id': '101e',
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'parent_addr': '0001:81:00.%d' % int(dev / 4),
                'numa_node': 0,
                "capabilities": {"vpd": {"card_serial_number": "MT2113X00000"}}
            }
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.parent_device = self.sriov_pf_devices_remote[int(dev / 4)]
            dev_obj.parent_device.child_devices.append(dev_obj)
            self.sriov_vf_devices_remote.append(dev_obj)

        self.vdpa_devices = []
        for dev in range(8):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:82:10.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % vf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.VDPA,
                'parent_addr': '0000:81:00.%d' % int(dev / 4),
                'numa_node': 0
            }
            dev_obj = objects.PciDevice.create(None, pci_dev)
            dev_obj.parent_device = self.sriov_pf_devices[int(dev / 4)]
            dev_obj.parent_device.child_devices.append(dev_obj)
            self.vdpa_devices.append(dev_obj)

        list(map(self.pci_stats.add_device, self.sriov_pf_devices))
        list(map(self.pci_stats.add_device, self.sriov_vf_devices))
        list(map(self.pci_stats.add_device, self.vdpa_devices))
        list(map(self.pci_stats.add_device, self.sriov_pf_devices_remote))
        list(map(self.pci_stats.add_device, self.sriov_vf_devices_remote))

    def test_consume_VDPA_requests(self):
        self._create_pci_devices()
        pci_requests = [
            objects.InstancePCIRequest(
                count=8, spec=[{'dev_type': 'vdpa'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(8, len(devs))
        self.assertEqual('vdpa', devs[0].dev_type)
        free_devs = self.pci_stats.get_free_devs()
        # Validate that the parents of these devs has been removed
        # from pools.
        for dev in devs:
            self.assertNotIn(dev.parent_addr,
                             [free_dev.address for free_dev in free_devs])

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
        self.assertEqual(0, len([d for d in free_devs
                                 if d.product_id == '1515']))

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
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests,
        )

    def test_consume_VF_and_PF_same_product_id_failed(self):
        self._create_pci_devices(pf_product_id=1515)
        pci_requests = [objects.InstancePCIRequest(count=9,
                            spec=[{'product_id': '1515'}])]
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests,
        )

    def test_consume_PF_not_remote_managed(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=2,
                            spec=[{'product_id': '1528',
                                   'dev_type': 'type-PF',
                                   PCI_REMOTE_MANAGED_TAG: 'false'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['1528']),
                            set([dev.product_id for dev in devs]))
        free_devs = self.pci_stats.get_free_devs()
        # Validate that there are no free devices left with the
        # product ID under test, as when allocating both available
        # PFs, its VFs should not be available.
        self.assertEqual(0, len([d for d in free_devs
                                 if d.product_id == '1528']))

    def test_consume_VF_requests_remote_managed(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=2,
                            spec=[{PCI_REMOTE_MANAGED_TAG: 'true'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['101e']),
                            set([dev.product_id for dev in devs]))
        free_devs = self.pci_stats.get_free_devs()
        # Validate that the parents of these VFs has been removed
        # from pools.
        for dev in devs:
            self.assertNotIn(dev.parent_addr,
                             [free_dev.address for free_dev in free_devs])

    def test_consume_VF_requests_remote_managed_filtered(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '101e',
                                   PCI_REMOTE_MANAGED_TAG: 'false'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '101e'}])]
        free_devs_before = self.pci_stats.get_free_devs()
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.pci_stats.consume_requests,
            pci_requests,
        )
        free_devs_after = self.pci_stats.get_free_devs()
        self.assertEqual(free_devs_before, free_devs_after)

    def test_consume_VF_requests_remote_managed_mix(self):
        self._create_pci_devices()
        pci_requests = [objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '101e',
                                   PCI_REMOTE_MANAGED_TAG: 'true'}]),
                        objects.InstancePCIRequest(count=1,
                            spec=[{'product_id': '1515',
                                   PCI_REMOTE_MANAGED_TAG: 'false'}])]
        devs = self.pci_stats.consume_requests(pci_requests)
        self.assertEqual(2, len(devs))
        self.assertEqual(set(['101e', '1515']),
                            set([dev.product_id for dev in devs]))
        free_devs = self.pci_stats.get_free_devs()
        # Validate that the parents of these VFs has been removed
        # from pools.
        for dev in devs:
            self.assertNotIn(dev.parent_addr,
                             [free_dev.address for free_dev in free_devs])
