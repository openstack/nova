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
from nova.scheduler.filters import num_instances_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestNumInstancesFilter(test.NoDBTestCase):

    def test_filter_num_instances_passes(self):
        self.flags(max_instances_per_host=5, group='filter_scheduler')
        self.filt_cls = num_instances_filter.NumInstancesFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 4})
        spec_obj = objects.RequestSpec()
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_filter_num_instances_fails(self):
        self.flags(max_instances_per_host=5, group='filter_scheduler')
        self.filt_cls = num_instances_filter.NumInstancesFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 5})
        spec_obj = objects.RequestSpec()
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_filter_aggregate_num_instances_value(self, agg_mock):
        self.flags(max_instances_per_host=4, group='filter_scheduler')
        self.filt_cls = num_instances_filter.AggregateNumInstancesFilter()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 5})
        spec_obj = objects.RequestSpec(context=mock.sentinel.ctx)
        agg_mock.return_value = set([])
        # No aggregate defined for that host.
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'max_instances_per_host')
        agg_mock.return_value = set(['6'])
        # Aggregate defined for that host.
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_filter_aggregate_num_instances_value_error(self, agg_mock):
        self.flags(max_instances_per_host=6, group='filter_scheduler')
        self.filt_cls = num_instances_filter.AggregateNumInstancesFilter()
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(context=mock.sentinel.ctx)
        agg_mock.return_value = set(['XXX'])
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'max_instances_per_host')
