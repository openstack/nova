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
Tests For Scheduler build failure weights.
"""

from nova.scheduler import weights
from nova.scheduler.weights import compute
from nova import test
from nova.tests.unit.scheduler import fakes


class BuildFailureWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(BuildFailureWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [compute.BuildFailureWeigher()]

    def _get_weighed_host(self, hosts):
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, {})

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'failed_builds': 0}),
            ('host2', 'node2', {'failed_builds': 1}),
            ('host3', 'node3', {'failed_builds': 10}),
            ('host4', 'node4', {'failed_builds': 100})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_build_failure_weigher_disabled(self):
        self.flags(build_failure_weight_multiplier=0.0,
                   group='filter_scheduler')
        hosts = self._get_all_hosts()
        weighed_hosts = self._get_weighed_host(hosts)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))

    def test_build_failure_weigher_scaled(self):
        self.flags(build_failure_weight_multiplier=1000.0,
                   group='filter_scheduler')
        hosts = self._get_all_hosts()
        weighed_hosts = self._get_weighed_host(hosts)
        self.assertEqual([0, -10, -100, -1000],
                         [wh.weight for wh in weighed_hosts])
