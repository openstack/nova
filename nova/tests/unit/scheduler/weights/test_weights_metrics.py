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
from nova.objects import fields
from nova.objects import monitor_metric
from nova.scheduler import weights
from nova.scheduler.weights import metrics
from nova import test
from nova.tests.unit.scheduler import fakes


idle = fields.MonitorMetricType.CPU_IDLE_TIME
kernel = fields.MonitorMetricType.CPU_KERNEL_TIME
user = fields.MonitorMetricType.CPU_USER_TIME


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
        def fake_metric(name, value):
            return monitor_metric.MonitorMetric(name=name, value=value)

        def fake_list(objs):
            m_list = [fake_metric(name, val) for name, val in objs]
            return monitor_metric.MonitorMetricList(objects=m_list)

        host_values = [
            ('host1', 'node1', {'metrics': fake_list([(idle, 512),
                                                      (kernel, 1)])}),
            ('host2', 'node2', {'metrics': fake_list([(idle, 1024),
                                                      (kernel, 2)])}),
            ('host3', 'node3', {'metrics': fake_list([(idle, 3072),
                                                      (kernel, 1)])}),
            ('host4', 'node4', {'metrics': fake_list([(idle, 8192),
                                                      (kernel, 0)])}),
            ('host5', 'node5', {'metrics': fake_list([(idle, 768),
                                                      (kernel, 0),
                                                      (user, 1)])}),
            ('host6', 'node6', {'metrics': fake_list([(idle, 2048),
                                                      (kernel, 0),
                                                      (user, 2)])}),
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def _do_test(self, settings, expected_weight, expected_host):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list, settings)
        self.assertEqual(expected_weight, weighed_host.weight)
        self.assertEqual(expected_host, weighed_host.obj.host)

    def test_single_resource_no_metrics(self):
        setting = [idle + '=1']
        hostinfo_list = [fakes.FakeHostState('host1', 'node1',
                                             {'metrics': None}),
                         fakes.FakeHostState('host2', 'node2',
                                             {'metrics': None})]
        self.assertRaises(exception.ComputeHostMetricNotFound,
                          self._get_weighed_host, hostinfo_list, setting)

    def test_single_resource(self):
        # host1: idle=512
        # host2: idle=1024
        # host3: idle=3072
        # host4: idle=8192
        # so, host4 should win:
        setting = [idle + '=1']
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource(self):
        # host1: idle=512,  kernel=1
        # host2: idle=1024, kernel=2
        # host3: idle=3072, kernel=1
        # host4: idle=8192, kernel=0
        # so, host2 should win:
        setting = [idle + '=0.0001', kernel + '=1']
        self._do_test(setting, 1.0, 'host2')

    def test_single_resource_duplicate_setting(self):
        # host1: idle=512
        # host2: idle=1024
        # host3: idle=3072
        # host4: idle=8192
        # so, host1 should win (sum of settings is negative):
        setting = [idle + '=-2', idle + '=1']
        self._do_test(setting, 1.0, 'host1')

    def test_single_resourcenegtive_ratio(self):
        # host1: idle=512
        # host2: idle=1024
        # host3: idle=3072
        # host4: idle=8192
        # so, host1 should win:
        setting = [idle + '=-1']
        self._do_test(setting, 1.0, 'host1')

    def test_multiple_resource_missing_ratio(self):
        # host1: idle=512,  kernel=1
        # host2: idle=1024, kernel=2
        # host3: idle=3072, kernel=1
        # host4: idle=8192, kernel=0
        # so, host4 should win:
        setting = [idle + '=0.0001', kernel]
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource_wrong_ratio(self):
        # host1: idle=512,  kernel=1
        # host2: idle=1024, kernel=2
        # host3: idle=3072, kernel=1
        # host4: idle=8192, kernel=0
        # so, host4 should win:
        setting = [idle + '=0.0001', kernel + ' = 2.0t']
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
                                   [idle + '=1'],
                                   [(idle, 1.0)])
        self._check_parsing_result(weigher,
                                   [idle + '=1', kernel + '=-2.1'],
                                   [(idle, 1.0), (kernel, -2.1)])
        self._check_parsing_result(weigher,
                                   [idle + '=a1', kernel + '=-2.1'],
                                   [(kernel, -2.1)])
        self._check_parsing_result(weigher,
                                   [idle, kernel + '=-2.1'],
                                   [(kernel, -2.1)])
        self._check_parsing_result(weigher,
                                   ['=5', kernel + '=-2.1'],
                                   [(kernel, -2.1)])

    def test_metric_not_found_required(self):
        setting = [idle + '=1', user + '=2']
        self.assertRaises(exception.ComputeHostMetricNotFound,
                          self._do_test,
                          setting,
                          8192,
                          'host4')

    def test_metric_not_found_non_required(self):
        # host1: idle=512,  kernel=1
        # host2: idle=1024, kernel=2
        # host3: idle=3072, kernel=1
        # host4: idle=8192, kernel=0
        # host5: idle=768, kernel=0, user=1
        # host6: idle=2048, kernel=0, user=2
        # so, host5 should win:
        self.flags(required=False, group='metrics')
        setting = [idle + '=0.0001', user + '=-1']
        self._do_test(setting, 1.0, 'host5')
