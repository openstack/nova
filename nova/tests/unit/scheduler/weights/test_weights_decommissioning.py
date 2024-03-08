# Copyright (c) 2024 SAP SE
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
Tests For Decommissioning weigher.
"""

from nova.scheduler import weights
from nova.scheduler.weights import decommissioning as decom
from nova.scheduler.weights.decommissioning import DECOM_TRAIT
from nova.scheduler.weights import ram
from nova import test
from nova.tests.unit.scheduler import fakes


class DecommissioningWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DecommissioningWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [ram.RAMWeigher(), decom.DecommissioningWeigher()]

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def test_decommissioning_weigher(self):
        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [DECOM_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [DECOM_TRAIT]

        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024
        })

        hosts = [host1, host2, host3]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        # host1,host2 are decommissioning, host3 should win
        self.assertEqual('host3', weighed_hosts[0].obj.host)
        # order determined by other weighers should not be changed
        self.assertEqual('host2', weighed_hosts[1].obj.host)
        self.assertEqual('host1', weighed_hosts[2].obj.host)

    def test_decommissioning_weight_multiplier(self):
        self.flags(decommissioning_weight_multiplier=0.0,
                   group='filter_scheduler')

        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [DECOM_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [DECOM_TRAIT]
        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024 * 1024
        })

        hosts = [host1, host2, host3]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        # decommissioning multiplier set to 0, host2 should win
        self.assertEqual('host2', weighed_hosts[0].obj.host)

    def test_decommissioning_ignoring_normal_hosts(self):
        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = ['CUSTOM_TRAIT']
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })

        hosts = [host1, host2]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        # no CUSTOM_DECOMMISSIONING trait, host2 should win
        self.assertEqual('host2', weighed_hosts[0].obj.host)
