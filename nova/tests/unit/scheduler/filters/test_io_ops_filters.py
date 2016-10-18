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


import mock

from nova import objects
from nova.scheduler.filters import io_ops_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestNumInstancesFilter(test.NoDBTestCase):

    def test_filter_num_iops_passes(self):
        self.flags(max_io_ops_per_host=8, group='filter_scheduler')
        self.filt_cls = io_ops_filter.IoOpsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        spec_obj = objects.RequestSpec()
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_filter_num_iops_fails(self):
        self.flags(max_io_ops_per_host=8, group='filter_scheduler')
        self.filt_cls = io_ops_filter.IoOpsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 8})
        spec_obj = objects.RequestSpec()
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_filter_num_iops_value(self, agg_mock):
        self.flags(max_io_ops_per_host=7, group='filter_scheduler')
        self.filt_cls = io_ops_filter.AggregateIoOpsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        spec_obj = objects.RequestSpec(context=mock.sentinel.ctx)
        agg_mock.return_value = set([])
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'max_io_ops_per_host')
        agg_mock.return_value = set(['8'])
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_filter_num_iops_value_error(self, agg_mock):
        self.flags(max_io_ops_per_host=8, group='filter_scheduler')
        self.filt_cls = io_ops_filter.AggregateIoOpsFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        agg_mock.return_value = set(['XXX'])
        spec_obj = objects.RequestSpec(context=mock.sentinel.ctx)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'max_io_ops_per_host')
