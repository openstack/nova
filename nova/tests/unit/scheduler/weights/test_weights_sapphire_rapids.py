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
Tests For SapphireRapidsWeigher.
"""

from nova.scheduler import weights
from nova.scheduler.weights import ram
from nova.scheduler.weights.sapphire_rapids import SapphireRapidsWeigher
from nova.scheduler.weights.sapphire_rapids import SR_TRAIT
from nova import test
from nova.tests.unit.scheduler import fakes


class SapphireRapidsWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [ram.RAMWeigher(), SapphireRapidsWeigher()]

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def test_mixed(self):
        """Test with BBs both having and not having the trait

        We'd expect the weigher to order the BBs not having the trait to the
        top.
        """
        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [SR_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [SR_TRAIT]

        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024
        })

        hosts = [host1, host2, host3]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        # host1,host2 are sapphire rapids, host3 should win
        self.assertEqual('host3', weighed_hosts[0].obj.host)
        # order determined by other weighers should not be changed
        self.assertEqual('host2', weighed_hosts[1].obj.host)
        self.assertEqual('host1', weighed_hosts[2].obj.host)

    def test_mixed_multiplier(self):
        """Test multiplier having an effect

        Using BBs both having and not having the trait, increasing the weight
        of the free RAM, we expect our multiplier being set much higher that
        the BBs not having the trait come out on top. If our multiplier
        wouldn't work, more RAM would win.
        """
        self.flags(sapphire_rapids_weight_multiplier=100.0,
                   group='filter_scheduler')
        self.flags(ram_weight_multiplier=10.0,
                   group='filter_scheduler')

        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [SR_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [SR_TRAIT]
        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024
        })
        host4 = fakes.FakeHostState('host4', 'node4', {
            'free_ram_mb': 1025
        })

        hosts = [host1, host2, host3, host4]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        # host4 should win even with less RAM, because host1 and host2 are
        # sapphire rapids and it has more RAM than host3
        self.assertEqual('host4', weighed_hosts[0].obj.host)
        # host3 should be second, because it's not a sapphire rapid, but has
        # less RAM than host4
        self.assertEqual('host3', weighed_hosts[1].obj.host)
        # order determined by other weighers should not be changed
        self.assertEqual('host2', weighed_hosts[2].obj.host)
        self.assertEqual('host1', weighed_hosts[3].obj.host)

    def test_mixed_mulitplier_0(self):
        """Test disabling the weigher via multiplier

        If we set our multiplier to 0, only the free RAM should specify the
        order.
        """
        self.flags(sapphire_rapids_weight_multiplier=0,
                   group='filter_scheduler')

        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [SR_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [SR_TRAIT]
        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024
        })

        hosts = [host1, host2, host3]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        self.assertEqual('host2', weighed_hosts[0].obj.host)
        self.assertEqual('host1', weighed_hosts[1].obj.host)
        self.assertEqual('host3', weighed_hosts[2].obj.host)

    def test_only_sapphire_rapids(self):
        """Test weighing only sapphire rapids BBs making no difference

        If we only weigh sapphire rapids BBs, the weight should be the same for
        all and thus only the RAM should specify the order i.e. it behaves as
        if the multiplier was set to 0.
        """
        host1 = fakes.FakeHostState('host1', 'node1', {
            'free_ram_mb': 1024 * 1024
        })
        host1.traits = [SR_TRAIT]
        host2 = fakes.FakeHostState('host2', 'node2', {
            'free_ram_mb': 1024 * 2048
        })
        host2.traits = [SR_TRAIT]
        host3 = fakes.FakeHostState('host3', 'node3', {
            'free_ram_mb': 1024
        })
        host3.traits = [SR_TRAIT]

        hosts = [host1, host2, host3]
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, {})

        self.assertEqual('host2', weighed_hosts[0].obj.host)
        self.assertEqual('host1', weighed_hosts[1].obj.host)
        self.assertEqual('host3', weighed_hosts[2].obj.host)
