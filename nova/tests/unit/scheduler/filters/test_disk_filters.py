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
from nova.scheduler.filters import disk_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestDiskFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestDiskFilter, self).setUp()

    def test_disk_filter_passes(self):
        filt_cls = disk_filter.DiskFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=1, ephemeral_gb=1, swap=512))
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13,
                 'disk_allocation_ratio': 1.0})
        self.assertTrue(filt_cls.host_passes(host, spec_obj))

    def test_disk_filter_fails(self):
        filt_cls = disk_filter.DiskFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(
                root_gb=10, ephemeral_gb=1, swap=1024))
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13,
                 'disk_allocation_ratio': 1.0})
        self.assertFalse(filt_cls.host_passes(host, spec_obj))

    def test_disk_filter_oversubscribe(self):
        filt_cls = disk_filter.DiskFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(
                root_gb=100, ephemeral_gb=18, swap=1024))
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12,
                 'disk_allocation_ratio': 10.0})
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        self.assertEqual(12 * 10.0, host.limits['disk_gb'])

    def test_disk_filter_oversubscribe_fail(self):
        filt_cls = disk_filter.DiskFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(
                root_gb=100, ephemeral_gb=19, swap=1024))
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12,
                 'disk_allocation_ratio': 10.0})
        self.assertFalse(filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_disk_filter_value_error(self, agg_mock):
        filt_cls = disk_filter.AggregateDiskFilter()
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(
                root_gb=1, ephemeral_gb=1, swap=1024))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_disk_mb': 3 * 1024,
                                    'total_usable_disk_gb': 1,
                                    'disk_allocation_ratio': 1.0})
        agg_mock.return_value = set(['XXX'])
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'disk_allocation_ratio')

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_disk_filter_default_value(self, agg_mock):
        filt_cls = disk_filter.AggregateDiskFilter()
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(
                root_gb=2, ephemeral_gb=1, swap=1024))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_disk_mb': 3 * 1024,
                                    'total_usable_disk_gb': 1,
                                    'disk_allocation_ratio': 1.0})
        # Uses global conf.
        agg_mock.return_value = set([])
        self.assertFalse(filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'disk_allocation_ratio')

        agg_mock.return_value = set(['2'])
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
