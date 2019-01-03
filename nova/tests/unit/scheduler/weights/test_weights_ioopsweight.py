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

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import io_ops
from nova import test
from nova.tests.unit.scheduler import fakes


class IoOpsWeigherTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IoOpsWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [io_ops.IoOpsWeigher()]
        self.ioops_weigher = io_ops.IoOpsWeigher()

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

    def test_io_ops_weight_multiplier(self):
        self.flags(io_ops_weight_multiplier=0.0,
                   group='filter_scheduler')
        host_attr = {'num_io_ops': 1}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)
        # By default, return the weight_multiplier configuration directly
        self.assertEqual(0.0, self.ioops_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'io_ops_weight_multiplier': '1'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(1.0, self.ioops_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'io_ops_weight_multiplier': '1'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'io_ops_weight_multiplier': '0.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(0.5, self.ioops_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(io_ops_weight_multiplier=0.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['host1', 'host2', 'host3', 'host4'],
                metadata={'io_ops_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs

        weights = self.weight_handler.get_weighed_objects(self.weighers,
                                                          hostinfo_list, {})
        weighed_host = weights[0]
        self.assertEqual(1.0 * 1.5, weighed_host.weight)
        self.assertEqual('host4', weighed_host.obj.host)
