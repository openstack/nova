# Copyright (c) 2016, Red Hat Inc.
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

"""Tests for Scheduler PCI weights."""

import copy

from nova import objects
from nova.pci import stats
from nova.scheduler import weights
from nova.scheduler.weights import pci
from nova import test
from nova.tests.unit import fake_pci_device_pools as fake_pci
from nova.tests.unit.scheduler import fakes


def _create_pci_pool(count):
    test_dict = copy.copy(fake_pci.fake_pool_dict)
    test_dict['count'] = count
    return objects.PciDevicePool.from_dict(test_dict)


def _create_pci_stats(counts):
    if counts is None:  # the pci_stats column is nullable
        return None

    pools = [_create_pci_pool(count) for count in counts]
    return stats.PciDeviceStats(pools)


class PCIWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PCIWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [pci.PCIWeigher()]
        self.pci_weigher = pci.PCIWeigher()

    def _get_weighed_hosts(self, hosts, request_spec):
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, request_spec)

    def _get_all_hosts(self, host_values):
        return [fakes.FakeHostState(
            host, node, {'pci_stats': _create_pci_stats(values)})
            for host, node, values in host_values]

    def test_multiplier_no_pci_empty_hosts(self):
        """Test weigher with a no PCI device instance on no PCI device hosts.

        Ensure that the host with no PCI devices receives the highest
        weighting.
        """
        hosts = [
            ('host1', 'node1', [3, 1]),  # 4 devs
            ('host2', 'node2', []),  # 0 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)

        # we don't request PCI devices
        spec_obj = objects.RequestSpec(pci_requests=None)

        # host2, which has the least PCI devices, should win
        weighed_host = self._get_weighed_hosts(hostinfo_list, spec_obj)[0]
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host2', weighed_host.obj.host)

    def test_multiplier_no_pci_non_empty_hosts(self):
        """Test weigher with a no PCI device instance on PCI device hosts.

        Ensure that the host with the least PCI devices receives the highest
        weighting.
        """
        hosts = [
            ('host1', 'node1', [2, 2, 2]),  # 6 devs
            ('host2', 'node2', [3, 1]),  # 4 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)

        # we don't request PCI devices
        spec_obj = objects.RequestSpec(pci_requests=None)

        # host2, which has the least free PCI devices, should win
        weighed_host = self._get_weighed_hosts(hostinfo_list, spec_obj)[0]
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host2', weighed_host.obj.host)

    def test_multiplier_with_pci(self):
        """Test weigher with a PCI device instance and a multiplier.

        Ensure that the host with the smallest number of free PCI devices
        capable of meeting the requirements of the instance is chosen,
        enforcing a stacking (rather than spreading) behavior.
        """
        # none of the hosts will have less than the number of devices required
        # by the instance: the NUMATopologyFilter takes care of this for us
        hosts = [
            ('host1', 'node1', [4, 1]),  # 5 devs
            ('host2', 'node2', [10]),  # 10 devs
            ('host3', 'node3', [1, 1, 1, 1]),  # 4 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)

        # we request PCI devices
        request = objects.InstancePCIRequest(count=4,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)

        # host3, which has the least free PCI devices, should win
        weighed_host = self._get_weighed_hosts(hostinfo_list, spec_obj)[0]
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host3', weighed_host.obj.host)

    def test_multiplier_with_many_pci(self):
        """Test weigher with a PCI device instance and huge hosts.

        Ensure that the weigher gracefully degrades when the number of PCI
        devices on the host exceeeds MAX_DEVS.
        """
        hosts = [
            ('host1', 'node1', [500]),  # 500 devs
            ('host2', 'node2', [2000]),  # 2000 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)

        # we request PCI devices
        request = objects.InstancePCIRequest(count=4,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)

        # we do not know the host as all have same weight
        weighed_hosts = self._get_weighed_hosts(hostinfo_list, spec_obj)
        for weighed_host in weighed_hosts:
            # the weigher normalizes all weights to 0 if they're all equal
            self.assertEqual(0.0, weighed_host.weight)

    def test_multiplier_none(self):
        """Test weigher with a PCI device instance and a 0.0 multiplier.

        Ensure that the 0.0 multiplier disables the weigher entirely.
        """
        self.flags(pci_weight_multiplier=0.0, group='filter_scheduler')

        hosts = [
            ('host1', 'node1', [4, 1]),  # 5 devs
            ('host2', 'node2', [10]),  # 10 devs
            ('host3', 'node3', [1, 1, 1, 1]),  # 4 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)

        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)

        # we do not know the host as all have same weight
        weighed_hosts = self._get_weighed_hosts(hostinfo_list, spec_obj)
        for weighed_host in weighed_hosts:
            # the weigher normalizes all weights to 0 if they're all equal
            self.assertEqual(0.0, weighed_host.weight)

    def test_pci_weigher_multiplier(self):
        self.flags(pci_weight_multiplier=0.0, group='filter_scheduler')
        hosts = [500]
        host1 = fakes.FakeHostState(
            'fake-host', 'node', {'pci_stats': _create_pci_stats(hosts)})
        # By default, return the weight_multiplier configuration directly
        self.assertEqual(0.0, self.pci_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'pci_weight_multiplier': '2'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(2.0, self.pci_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'pci_weight_multiplier': '2'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'pci_weight_multiplier': '1.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(1.5, self.pci_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(pci_weight_multiplier=0.0, group='filter_scheduler')
        hosts = [
            ('host1', 'node1', [2, 2, 2]),  # 6 devs
            ('host2', 'node2', [3, 1]),  # 4 devs
        ]
        hostinfo_list = self._get_all_hosts(hosts)
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['host1', 'host2'],
                metadata={'pci_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs

        spec_obj = objects.RequestSpec(pci_requests=None)

        # host2, which has the least free PCI devices, should win
        weighed_host = self._get_weighed_hosts(hostinfo_list, spec_obj)[0]
        self.assertEqual(1.5, weighed_host.weight)
        self.assertEqual('host2', weighed_host.obj.host)
