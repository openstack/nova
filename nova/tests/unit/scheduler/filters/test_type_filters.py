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
from nova.scheduler.filters import type_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestTypeFilter(test.NoDBTestCase):

    def test_type_filter(self):
        self.filt_cls = type_filter.TypeAffinityFilter()
        host = fakes.FakeHostState('fake_host', 'fake_node', {})
        host.instances = {}
        target_id = 1
        filter_properties = {'context': mock.MagicMock(),
                             'instance_type': {'id': target_id}}
        # True since no instances on host
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        # Add an instance with the same instance_type_id
        inst1 = objects.Instance(uuid='aa', instance_type_id=target_id)
        host.instances = {inst1.uuid: inst1}
        # True since only same instance_type_id on host
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        # Add an instance with a different instance_type_id
        diff_type = target_id + 1
        inst2 = objects.Instance(uuid='bb', instance_type_id=diff_type)
        host.instances.update({inst2.uuid: inst2})
        # False since host now has an instance of a different type
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
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
        agg_mock.assert_called_once_with(host, 'instance_type')
        # False since type matches aggregate, metadata
        self.assertFalse(self.filt_cls.host_passes(host, filter2_properties))
