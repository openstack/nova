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
Tests For Scheduler hypervisor version weights.
"""

from nova.scheduler import weights
from nova.scheduler.weights import hypervisor_version
from nova import test
from nova.tests.unit.scheduler import fakes


class HypervisorVersionWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [hypervisor_version.HypervisorVersionWeigher()]

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'hypervisor_version': 1}),
            ('host2', 'node2', {'hypervisor_version': 200}),
            ('host3', 'node3', {'hypervisor_version': 100}),
            ('host4', 'node4', {'hypervisor_version': 1000}),
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_multiplier_default(self):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier_default_full_ordering(self):
        hostinfo_list = self._get_all_hosts()
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list, {}
        )
        expected_hosts = [fakes.FakeHostState(host, node, values)
                for host, node, values in [
            ('host4', 'node4', {'hypervisor_version': 1000}),
            ('host2', 'node2', {'hypervisor_version': 200}),
            ('host3', 'node3', {'hypervisor_version': 100}),
            ('host1', 'node1', {'hypervisor_version': 1}),
        ]]
        for actual, expected in zip(
            weighed_hosts,
            expected_hosts
        ):
            self.assertEqual(actual.obj.host, expected.host)

    def test_multiplier_none(self):
        multi = 0.0
        self.flags(
            hypervisor_version_weight_multiplier=multi,
            group='filter_scheduler'
        )
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(multi, weighed_host.weight)

    def test_multiplier_positive(self):
        multi = 2.0
        self.flags(
            hypervisor_version_weight_multiplier=multi,
            group='filter_scheduler'
        )
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0 * multi, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier_negative(self):
        multi = -1.0
        self.flags(
            hypervisor_version_weight_multiplier=multi,
            group='filter_scheduler'
        )
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual('host1', weighed_host.obj.host)
