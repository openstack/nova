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
Tests For Scheduler weights.
"""

from nova import exception
from nova.scheduler import host_manager
from nova.scheduler import weights
from nova.scheduler.weights import io_ops
from nova.scheduler.weights import metrics
from nova.scheduler.weights import ram
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit.scheduler import fakes


class TestWeighedHost(test.NoDBTestCase):
    def test_dict_conversion(self):
        host_state = fakes.FakeHostState('somehost', None, {})
        host = weights.WeighedHost(host_state, 'someweight')
        expected = {'weight': 'someweight',
                    'host': 'somehost'}
        self.assertThat(host.to_dict(), matchers.DictMatches(expected))

    def test_all_weighers(self):
        classes = weights.all_weighers()
        self.assertIn(ram.RAMWeigher, classes)
        self.assertIn(metrics.MetricsWeigher, classes)
        self.assertIn(io_ops.IoOpsWeigher, classes)


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
        self.flags(ram_weight_multiplier=0.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)

    def test_ram_filter_multiplier2(self):
        self.flags(ram_weight_multiplier=2.0)
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
        self.flags(ram_weight_multiplier=1.0)
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


class MetricsWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MetricsWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [metrics.MetricsWeigher()]

    def _get_weighed_host(self, hosts, setting, weight_properties=None):
        if not weight_properties:
            weight_properties = {}
        self.flags(weight_setting=setting, group='metrics')
        self.weighers[0]._parse_setting()
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        def fake_metric(value):
            return host_manager.MetricItem(value=value, timestamp='fake-time',
                                           source='fake-source')

        host_values = [
            ('host1', 'node1', {'metrics': {'foo': fake_metric(512),
                                            'bar': fake_metric(1)}}),
            ('host2', 'node2', {'metrics': {'foo': fake_metric(1024),
                                            'bar': fake_metric(2)}}),
            ('host3', 'node3', {'metrics': {'foo': fake_metric(3072),
                                            'bar': fake_metric(1)}}),
            ('host4', 'node4', {'metrics': {'foo': fake_metric(8192),
                                            'bar': fake_metric(0)}}),
            ('host5', 'node5', {'metrics': {'foo': fake_metric(768),
                                            'bar': fake_metric(0),
                                            'zot': fake_metric(1)}}),
            ('host6', 'node6', {'metrics': {'foo': fake_metric(2048),
                                            'bar': fake_metric(0),
                                            'zot': fake_metric(2)}}),
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def _do_test(self, settings, expected_weight, expected_host):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list, settings)
        self.assertEqual(expected_weight, weighed_host.weight)
        self.assertEqual(expected_host, weighed_host.obj.host)

    def test_single_resource(self):
        # host1: foo=512
        # host2: foo=1024
        # host3: foo=3072
        # host4: foo=8192
        # so, host4 should win:
        setting = ['foo=1']
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host2 should win:
        setting = ['foo=0.0001', 'bar=1']
        self._do_test(setting, 1.0, 'host2')

    def test_single_resourcenegtive_ratio(self):
        # host1: foo=512
        # host2: foo=1024
        # host3: foo=3072
        # host4: foo=8192
        # so, host1 should win:
        setting = ['foo=-1']
        self._do_test(setting, 1.0, 'host1')

    def test_multiple_resource_missing_ratio(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host4 should win:
        setting = ['foo=0.0001', 'bar']
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource_wrong_ratio(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host4 should win:
        setting = ['foo=0.0001', 'bar = 2.0t']
        self._do_test(setting, 1.0, 'host4')

    def _check_parsing_result(self, weigher, setting, results):
        self.flags(weight_setting=setting, group='metrics')
        weigher._parse_setting()
        self.assertEqual(len(weigher.setting), len(results))
        for item in results:
            self.assertIn(item, weigher.setting)

    def test_parse_setting(self):
        weigher = self.weighers[0]
        self._check_parsing_result(weigher,
                                   ['foo=1'],
                                   [('foo', 1.0)])
        self._check_parsing_result(weigher,
                                   ['foo=1', 'bar=-2.1'],
                                   [('foo', 1.0), ('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['foo=a1', 'bar=-2.1'],
                                   [('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['foo', 'bar=-2.1'],
                                   [('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['=5', 'bar=-2.1'],
                                   [('bar', -2.1)])

    def test_metric_not_found_required(self):
        setting = ['foo=1', 'zot=2']
        self.assertRaises(exception.ComputeHostMetricNotFound,
                          self._do_test,
                          setting,
                          8192,
                          'host4')

    def test_metric_not_found_non_required(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # host5: foo=768, bar=0, zot=1
        # host6: foo=2048, bar=0, zot=2
        # so, host5 should win:
        self.flags(required=False, group='metrics')
        setting = ['foo=0.0001', 'zot=-1']
        self._do_test(setting, 1.0, 'host5')


class IoOpsWeigherTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IoOpsWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [io_ops.IoOpsWeigher()]

    def _get_weighed_host(self, hosts, io_ops_weight_multiplier):
        if io_ops_weight_multiplier is not None:
            self.flags(io_ops_weight_multiplier=io_ops_weight_multiplier)
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
