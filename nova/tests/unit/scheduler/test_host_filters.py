# Copyright 2011 OpenStack Foundation  # All Rights Reserved.
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
Tests For Scheduler Host Filters.
"""
from unittest import mock

from nova.scheduler import filters
from nova.scheduler.filters import all_hosts_filter
from nova.scheduler.filters import compute_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class HostFiltersTestCase(test.NoDBTestCase):

    def test_filter_handler(self):
        # Double check at least a couple of known filters exist
        filter_handler = filters.HostFilterHandler()
        classes = filter_handler.get_matching_classes(
                ['nova.scheduler.filters.all_filters'])
        self.assertIn(all_hosts_filter.AllHostsFilter, classes)
        self.assertIn(compute_filter.ComputeFilter, classes)

    def test_host_info_requiring_instance_ids(self):
        filter_handler = filters.HostFilterHandler()
        filter_a = mock.Mock()
        filter_b = mock.Mock()

        filter_a.host_info_requiring_instance_ids.return_value = {'a'}
        filter_b.host_info_requiring_instance_ids.return_value = {'b'}

        mock_filter = [filter_a, filter_b]
        spec_obj = mock.sentinel.spec_obj
        result = filter_handler.host_info_requiring_instance_ids(mock_filter,
                                                                 spec_obj)
        self.assertEqual({'a', 'b'}, result)

    def test_all_host_filter(self):
        filt_cls = all_hosts_filter.AllHostsFilter()
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, {}))
