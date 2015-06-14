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
Tests For Scheduler metrics weights.
"""

from nova import exception
from nova.scheduler import host_manager
from nova.scheduler import weights
from nova.scheduler.weights import metrics
from nova import test
from nova.tests.unit.scheduler import fakes


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
