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

import datetime

from nova import objects
from nova.scheduler.filters import metrics_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestMetricsFilter(test.NoDBTestCase):

    def test_metrics_filter_pass(self):
        _ts_now = datetime.datetime(2015, 11, 11, 11, 0, 0)
        obj1 = objects.MonitorMetric(name='cpu.frequency',
                                     value=1000,
                                     timestamp=_ts_now,
                                     source='nova.virt.libvirt.driver')
        obj2 = objects.MonitorMetric(name='numa.membw.current',
                                     numa_membw_values={"0": 10, "1": 43},
                                     timestamp=_ts_now,
                                     source='nova.virt.libvirt.driver')
        metrics_list = objects.MonitorMetricList(objects=[obj1, obj2])
        self.flags(weight_setting=[
            'cpu.frequency=1', 'numa.membw.current=2'], group='metrics')
        filt_cls = metrics_filter.MetricsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   attribute_dict={'metrics': metrics_list})
        self.assertTrue(filt_cls.host_passes(host, None))

    def test_metrics_filter_missing_metrics(self):
        _ts_now = datetime.datetime(2015, 11, 11, 11, 0, 0)
        obj1 = objects.MonitorMetric(name='cpu.frequency',
                                     value=1000,
                                     timestamp=_ts_now,
                                     source='nova.virt.libvirt.driver')
        metrics_list = objects.MonitorMetricList(objects=[obj1])
        self.flags(weight_setting=['foo=1', 'bar=2'], group='metrics')
        filt_cls = metrics_filter.MetricsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   attribute_dict={'metrics': metrics_list})
        self.assertFalse(filt_cls.host_passes(host, None))
