# Copyright 2011-2012 OpenStack Foundation
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
Tests For Scheduler RAM weights.
"""

from nova.scheduler import weights
from nova.scheduler.weights import ram
from nova import test
from nova.tests.unit.scheduler import fakes


class RamWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(RamWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [ram.RAMWeigher()]

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'free_ram_mb': 512}),
            ('host2', 'node2', {'free_ram_mb': 1024}),
            ('host3', 'node3', {'free_ram_mb': 3072}),
            ('host4', 'node4', {'free_ram_mb': 8192})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_ram_filter_multiplier1(self):
        self.flags(ram_weight_multiplier=0.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)

    def test_ram_filter_multiplier2(self):
        self.flags(ram_weight_multiplier=2.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0 * 2, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_ram_filter_negative(self):
        self.flags(ram_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        host_attr = {'id': 100, 'memory_mb': 8192, 'free_ram_mb': -512}
        host_state = fakes.FakeHostState('negative', 'negative', host_attr)
        hostinfo_list = list(hostinfo_list) + [host_state]

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192
        # negativehost: free_ram_mb=-512

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
