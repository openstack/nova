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

import six

from nova import objects
from nova.scheduler.filters import type_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from nova.tests import uuidsentinel as uuids


class TestTypeFilter(test.NoDBTestCase):

    def test_type_filter(self):
        with mock.patch.object(type_filter.LOG, 'warning') as mock_warning:
            self.filt_cls = type_filter.TypeAffinityFilter()
        # make sure we logged a deprecation warning
        self.assertEqual(1, mock_warning.call_count)
        self.assertIn('TypeAffinityFilter is deprecated for removal',
                      six.text_type(mock_warning.call_args_list[0][0]))
        host = fakes.FakeHostState('fake_host', 'fake_node', {})
        host.instances = {}
        target_id = 1
        spec_obj = objects.RequestSpec(
            context=mock.MagicMock(),
            flavor=objects.Flavor(id=target_id))
        # True since no instances on host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # Add an instance with the same instance_type_id
        inst1 = objects.Instance(uuid=uuids.instance_1,
                                 instance_type_id=target_id)
        host.instances = {inst1.uuid: inst1}
        # True since only same instance_type_id on host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # Add an instance with a different instance_type_id
        diff_type = target_id + 1
        inst2 = objects.Instance(uuid=uuids.instance_2,
                                 instance_type_id=diff_type)
        host.instances.update({inst2.uuid: inst2})
        # False since host now has an instance of a different type
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_type_filter_no_metadata(self, agg_mock):
        self.filt_cls = type_filter.AggregateTypeAffinityFilter()

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake1'))
        host = fakes.FakeHostState('fake_host', 'fake_node', {})

        # tests when no instance_type is defined for aggregate
        agg_mock.return_value = set([])
        # True as no instance_type set for aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        agg_mock.assert_called_once_with(host, 'instance_type')

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_type_filter_single_instance_type(self, agg_mock):
        self.filt_cls = type_filter.AggregateTypeAffinityFilter()

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake1'))
        spec_obj2 = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake2'))
        host = fakes.FakeHostState('fake_host', 'fake_node', {})

        # tests when a single instance_type is defined for an aggregate
        # using legacy single value syntax
        agg_mock.return_value = set(['fake1'])

        # True as instance_type is allowed for aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

        # False as instance_type is not allowed for aggregate
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj2))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_type_filter_multi_aggregate(self, agg_mock):
        self.filt_cls = type_filter.AggregateTypeAffinityFilter()

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake1'))
        spec_obj2 = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake2'))
        spec_obj3 = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake3'))
        host = fakes.FakeHostState('fake_host', 'fake_node', {})

        # tests when a single instance_type is defined for multiple aggregates
        # using legacy single value syntax
        agg_mock.return_value = set(['fake1', 'fake2'])

        # True as instance_type is allowed for first aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # True as instance_type is allowed for second aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj2))
        # False as instance_type is not allowed for aggregates
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj3))

    @mock.patch('nova.scheduler.filters.utils.aggregate_values_from_key')
    def test_aggregate_type_filter_multi_instance_type(self, agg_mock):
        self.filt_cls = type_filter.AggregateTypeAffinityFilter()

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake1'))
        spec_obj2 = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake2'))
        spec_obj3 = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(name='fake3'))
        host = fakes.FakeHostState('fake_host', 'fake_node', {})

        # tests when multiple instance_types are defined for aggregate
        agg_mock.return_value = set(['fake1,fake2'])

        # True as instance_type is allowed for aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # True as instance_type is allowed for aggregate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj2))
        # False as instance_type is not allowed for aggregate
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj3))
