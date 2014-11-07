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

from nova.scheduler.filters import type_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestTypeFilter(test.NoDBTestCase):

    @mock.patch('nova.db.instance_get_all_by_host_and_not_type')
    def test_type_filter(self, get_mock):
        self.filt_cls = type_filter.TypeAffinityFilter()

        host = fakes.FakeHostState('fake_host', 'fake_node', {})
        filter_properties = {'context': mock.MagicMock(),
                             'instance_type': {'id': 'fake1'}}
        get_mock.return_value = []
        # True since empty
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        get_mock.assert_called_once_with(
            mock.ANY,  # context...
            'fake_host',
            'fake1'
        )
        get_mock.return_value = [mock.sentinel.instances]
        # False since not empty
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_db')
    def test_aggregate_type_filter(self, agg_mock):
        self.filt_cls = type_filter.AggregateTypeAffinityFilter()

        filter_properties = {'context': mock.sentinel.ctx,
                             'instance_type': {'name': 'fake1'}}
        filter2_properties = {'context': mock.sentinel.ctx,
                             'instance_type': {'name': 'fake2'}}
        host = fakes.FakeHostState('fake_host', 'fake_node', {})
        agg_mock.return_value = set(['fake1'])
        # True since no aggregates
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        agg_mock.assert_called_once_with(mock.sentinel.ctx, 'fake_host',
                                         'instance_type')
        # False since type matches aggregate, metadata
        self.assertFalse(self.filt_cls.host_passes(host, filter2_properties))
