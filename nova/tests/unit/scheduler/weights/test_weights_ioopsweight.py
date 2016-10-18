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
Tests For Scheduler IoOpsWeigher weights
"""

from nova.scheduler import weights
from nova.scheduler.weights import io_ops
from nova import test
from nova.tests.unit.scheduler import fakes


class IoOpsWeigherTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IoOpsWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [io_ops.IoOpsWeigher()]

    def _get_weighed_host(self, hosts, io_ops_weight_multiplier):
        if io_ops_weight_multiplier is not None:
            self.flags(io_ops_weight_multiplier=io_ops_weight_multiplier,
                       group='filter_scheduler')
        return self.weight_handler.get_weighed_objects(self.weighers,
                                                       hosts, {})[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'num_io_ops': 1}),
            ('host2', 'node2', {'num_io_ops': 2}),
            ('host3', 'node3', {'num_io_ops': 0}),
            ('host4', 'node4', {'num_io_ops': 4})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def _do_test(self, io_ops_weight_multiplier, expected_weight,
                 expected_host):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              io_ops_weight_multiplier)
        self.assertEqual(weighed_host.weight, expected_weight)
        if expected_host:
            self.assertEqual(weighed_host.obj.host, expected_host)

    def test_io_ops_weight_multiplier_by_default(self):
        self._do_test(io_ops_weight_multiplier=None,
                      expected_weight=0.0,
                      expected_host='host3')

    def test_io_ops_weight_multiplier_zero_value(self):
        # We do not know the host, all have same weight.
        self._do_test(io_ops_weight_multiplier=0.0,
                      expected_weight=0.0,
                      expected_host=None)

    def test_io_ops_weight_multiplier_positive_value(self):
        self._do_test(io_ops_weight_multiplier=2.0,
                      expected_weight=2.0,
                      expected_host='host4')
