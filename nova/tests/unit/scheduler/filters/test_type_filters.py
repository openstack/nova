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

import logging

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
        spec_obj = objects.RequestSpec(
            context=mock.MagicMock(),
            flavor=objects.Flavor(id=target_id))
        # True since no instances on host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # Add an instance with the same instance_type_id
        inst1 = objects.Instance(uuid='aa', instance_type_id=target_id)
        host.instances = {inst1.uuid: inst1}
        # True since only same instance_type_id on host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # Add an instance with a different instance_type_id
        diff_type = target_id + 1
        inst2 = objects.Instance(uuid='bb', instance_type_id=diff_type)
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


class TestAggregateTypeExtraSpecsAffinityFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestAggregateTypeExtraSpecsAffinityFilter, self).setUp()
        self.filt_cls = type_filter.AggregateTypeExtraSpecsAffinityFilter()

        self.aggr_no_extraspecs = objects.Aggregate(context='test')
        self.aggr_no_extraspecs.metadata = {}

        self.aggr_invalid_extraspecs = objects.Aggregate(context='test')
        self.aggr_invalid_extraspecs.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=large'}

        self.aggr_valid_extraspecs = objects.Aggregate(context='test')
        self.aggr_valid_extraspecs.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=small'}

        self.aggr_optional_large = objects.Aggregate(context='test')
        self.aggr_optional_large.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=large,hw:mem_page_size=~'}

        self.aggr_optional_small = objects.Aggregate(context='test')
        self.aggr_optional_small.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=small,hw:mem_page_size=~'}

        self.aggr_optional_first = objects.Aggregate(context='test')
        self.aggr_optional_first.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=~,hw:mem_page_size=small,hw:mem_page_size=any'}

        self.aggr_optional_last = objects.Aggregate(context='test')
        self.aggr_optional_last.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=any,hw:mem_page_size=small,hw:mem_page_size=~'}

        self.aggr_optional_middle = objects.Aggregate(context='test')
        self.aggr_optional_middle.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=any,hw:mem_page_size=~,hw:mem_page_size=small'}

        self.aggr_any = objects.Aggregate(context='test')
        self.aggr_any.metadata = {'flavor_extra_spec': 'hw:mem_page_size=*'}

        self.aggr_nopresent = objects.Aggregate(context='test')
        self.aggr_nopresent.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=!'}

        self.aggr_asterisk_inline = objects.Aggregate(context='test')
        self.aggr_asterisk_inline.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=*value'}

        self.aggr_tilde_inline = objects.Aggregate(context='test')
        self.aggr_tilde_inline.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=value~'}

        self.aggr_exclamation_inline = objects.Aggregate(context='test')
        self.aggr_exclamation_inline.metadata = {'flavor_extra_spec':
            'hw:mem_page_size=va!lue'}

        self.rs_extraspecs = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(extra_specs={'hw:mem_page_size': 'small'}))
        self.rs_no_extraspecs = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor())

    @mock.patch.object(logging.LoggerAdapter, 'info')
    def test_parse_extra_spec_key_pairs(self, mock_logging):
        mock_logging.return_value = True
        self.filt_cls._parse_extra_spec_key_pairs("key=value=foobar")
        mock_logging.assert_called_with(
            ("Value string has an '=' char: key = '%(key)s', value = "
             "'%(value)s'. Check if it's malformed"),
            {'value': 'value=foobar', 'key': 'key'})
        mock_logging.reset_mock()
        self.filt_cls._parse_extra_spec_key_pairs("key=value")
        mock_logging.assert_not_called()

    @mock.patch.object(logging.LoggerAdapter, 'info')
    def test_sentinel_values_inline(self, mock_logging):
        mock_logging.return_value = True
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state_aggregates = [self.aggr_asterisk_inline,
            self.aggr_tilde_inline, self.aggr_exclamation_inline]
        chars = ['*', '~', '!']
        values = ['*value', 'value~', 'va!lue']
        for host_state_aggregate, char, value in zip(host_state_aggregates,
                                                     chars, values):
            host_state.aggregates = [host_state_aggregate]
            self.filt_cls.host_passes(host_state, self.rs_extraspecs)
            mock_logging.assert_called_with(
                ("Value string has '%(chars)s' char(s): key = '%(key)s', "
                 "value = '%(value)s'. Check if it's malformed"),
                {'chars': [char], 'value': value, 'key': 'hw:mem_page_size'})
            mock_logging.reset_mock()

    @mock.patch.object(logging.LoggerAdapter, 'info')
    def test_no_sentinel_values_inline(self, mock_logging):
        mock_logging.return_value = True
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates = [self.aggr_valid_extraspecs]
        self.filt_cls.host_passes(host_state, self.rs_extraspecs)
        mock_logging.assert_not_called()

    def test_aggregate_type_extra_specs_ha_no_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_no_extraspecs)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_ha_wrong_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_invalid_extraspecs)
        self.assertFalse(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_ha_right_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_valid_extraspecs)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_2ha_noextra_wrong(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_no_extraspecs)
        host_state.aggregates.append(self.aggr_invalid_extraspecs)
        self.assertFalse(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_2ha_noextra_right(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_no_extraspecs)
        host_state.aggregates.append(self.aggr_valid_extraspecs)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_2ha_wrong_right(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_invalid_extraspecs)
        host_state.aggregates.append(self.aggr_valid_extraspecs)
        self.assertFalse(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_any_and_more_large(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_optional_large)
        self.assertFalse(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_any_and_more_small(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_optional_small)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_any_and_more_no_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_optional_large)
        self.assertTrue(self.filt_cls.host_passes(host_state,
                                                  self.rs_no_extraspecs))

    def test_aggregate_type_extra_specs_any_order(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        for host_state_aggregate in [self.aggr_optional_first,
                                     self.aggr_optional_last,
                                     self.aggr_optional_middle]:
            host_state.aggregates = [host_state_aggregate]
            self.assertTrue(self.filt_cls.host_passes(host_state,
                self.rs_extraspecs))

    def test_aggregate_type_extra_specs_asterisk(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_any)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_asterisk_no_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_any)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_no_extraspecs))

    def test_aggregate_type_extra_specs_nospec(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_nopresent)
        self.assertFalse(self.filt_cls.host_passes(host_state,
            self.rs_extraspecs))

    def test_aggregate_type_extra_specs_nospec_no_extraspecs(self):
        host_state = fakes.FakeHostState('host1', 'compute', {})
        host_state.aggregates.append(self.aggr_nopresent)
        self.assertTrue(self.filt_cls.host_passes(host_state,
            self.rs_no_extraspecs))
