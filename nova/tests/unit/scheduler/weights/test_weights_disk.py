# Copyright 2011-2016 OpenStack Foundation
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
"""
Tests For Scheduler disk weights.
"""

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import disk
from nova import test
from nova.tests.unit.scheduler import fakes


class DiskWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DiskWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [disk.DiskWeigher()]
        self.disk_weigher = disk.DiskWeigher()

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'free_disk_mb': 5120}),
            ('host2', 'node2', {'free_disk_mb': 10240}),
            ('host3', 'node3', {'free_disk_mb': 30720}),
            ('host4', 'node4', {'free_disk_mb': 81920})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_hosts()

        # host1: free_disk_mb=5120
        # host2: free_disk_mb=10240
        # host3: free_disk_mb=30720
        # host4: free_disk_mb=81920

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_disk_filter_multiplier1(self):
        self.flags(disk_weight_multiplier=0.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: free_disk_mb=5120
        # host2: free_disk_mb=10240
        # host3: free_disk_mb=30720
        # host4: free_disk_mb=81920

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)

    def test_disk_filter_multiplier2(self):
        self.flags(disk_weight_multiplier=2.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: free_disk_mb=5120
        # host2: free_disk_mb=10240
        # host3: free_disk_mb=30720
        # host4: free_disk_mb=81920

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0 * 2, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_disk_filter_negative(self):
        self.flags(disk_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        host_attr = {'id': 100, 'disk_mb': 81920, 'free_disk_mb': -5120}
        host_state = fakes.FakeHostState('negative', 'negative', host_attr)
        hostinfo_list = list(hostinfo_list) + [host_state]

        # host1: free_disk_mb=5120
        # host2: free_disk_mb=10240
        # host3: free_disk_mb=30720
        # host4: free_disk_mb=81920
        # negativehost: free_disk_mb=-5120

        # so, host4 should win
        weights = self.weight_handler.get_weighed_objects(self.weighers,
                                                          hostinfo_list, {})

        weighed_host = weights[0]
        self.assertEqual(1, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

        # and negativehost should lose
        weighed_host = weights[-1]
        self.assertEqual(0, weighed_host.weight)
        self.assertEqual('negative', weighed_host.obj.host)

    def test_disk_weigher_multiplier(self):
        self.flags(disk_weight_multiplier=-1.0, group='filter_scheduler')
        host_attr = {'free_disk_mb': 5120}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)
        # By default, return the weight_multiplier configuration directly
        self.assertEqual(-1, self.disk_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'disk_weight_multiplier': '2'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(2.0, self.disk_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'disk_weight_multiplier': '2'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'disk_weight_multiplier': '1.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(1.5, self.disk_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(disk_weight_multiplier=-1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['host1', 'host2', 'host3', 'host4'],
                metadata={'disk_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs
        # host1: free_disk_mb=5120
        # host2: free_disk_mb=10240
        # host3: free_disk_mb=30720
        # host4: free_disk_mb=81920

        # so, host4 should win:
        weights = self.weight_handler.get_weighed_objects(self.weighers,
                                                          hostinfo_list, {})
        weighed_host = weights[0]
        self.assertEqual(1.0 * 1.5, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)
