# Copyright 2016, Red Hat Inc.
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
Tests For Scheduler CPU weights.
"""

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import cpu
from nova import test
from nova.tests.unit.scheduler import fakes


class CPUWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(CPUWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [cpu.CPUWeigher()]
        self.cpu_weigher = cpu.CPUWeigher()

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'vcpus_total': 8, 'vcpus_used': 8,
                                'cpu_allocation_ratio': 1.0}),  # 0 free
            ('host2', 'node2', {'vcpus_total': 4, 'vcpus_used': 2,
                                'cpu_allocation_ratio': 1.0}),  # 2 free
            ('host3', 'node3', {'vcpus_total': 6, 'vcpus_used': 0,
                                'cpu_allocation_ratio': 1.0}),  # 6 free
            ('host4', 'node4', {'vcpus_total': 8, 'vcpus_used': 0,
                                'cpu_allocation_ratio': 2.0}),  # 16 free
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_multiplier_default(self):
        hostinfo_list = self._get_all_hosts()

        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=16

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier_none(self):
        self.flags(cpu_weight_multiplier=0.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=16

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)

    def test_multiplier_positive(self):
        self.flags(cpu_weight_multiplier=2.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=16

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0 * 2, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier_negative(self):
        self.flags(cpu_weight_multiplier=-1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=16

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual('host1', weighed_host.obj.host)

    def test_negative_host(self):
        self.flags(cpu_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        host_attr = {'vcpus_total': 4, 'vcpus_used': 6,
                     'cpu_allocation_ratio': 1.0}
        host_state = fakes.FakeHostState('negative', 'negative', host_attr)
        hostinfo_list = list(hostinfo_list) + [host_state]

        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=16
        # negative: vcpus_free=-2

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

    def test_cpu_weigher_multiplier(self):
        self.flags(cpu_weight_multiplier=-1.0, group='filter_scheduler')
        host_attr = {'vcpus_total': 4, 'vcpus_used': 6,
                     'cpu_allocation_ratio': 1.0}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)
        # By default, return the cpu_weight_multiplier configuration directly
        self.assertEqual(-1, self.cpu_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '2'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(2.0, self.cpu_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '2'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '1.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(1.5, self.cpu_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(cpu_weight_multiplier=-1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['host1', 'host2', 'host3', 'host4'],
                metadata={'cpu_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs
        # host1: vcpus_free=0
        # host2: vcpus_free=2
        # host3: vcpus_free=6
        # host4: vcpus_free=8

        # so, host4 should win
        weights = self.weight_handler.get_weighed_objects(self.weighers,
                                                          hostinfo_list, {})
        weighed_host = weights[0]
        self.assertEqual(1.5, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)
