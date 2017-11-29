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
from nova.scheduler.filters import aggregate_instance_extra_specs as agg_specs
from nova import test
from nova.tests.unit.scheduler import fakes


@mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
class TestAggregateInstanceExtraSpecsFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestAggregateInstanceExtraSpecsFilter, self).setUp()
        self.filt_cls = agg_specs.AggregateInstanceExtraSpecsFilter()

    def test_aggregate_filter_passes_no_extra_specs(self, agg_mock):
        capabilities = {'opt1': 1, 'opt2': 2}

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(memory_mb=1024))
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        self.assertFalse(agg_mock.called)

    def test_aggregate_filter_passes_empty_extra_specs(self, agg_mock):
        capabilities = {'opt1': 1, 'opt2': 2}

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(memory_mb=1024, extra_specs={}))
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        self.assertFalse(agg_mock.called)

    def _do_test_aggregate_filter_extra_specs(self, especs, passes):
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(memory_mb=1024, extra_specs=especs))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_ram_mb': 1024})
        assertion = self.assertTrue if passes else self.assertFalse
        assertion(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_filter_passes_extra_specs_simple(self, agg_mock):
        agg_mock.return_value = {'opt1': set(['1']), 'opt2': set(['2'])}
        especs = {
            # Un-scoped extra spec
            'opt1': '1',
            # Scoped extra spec that applies to this filter
            'aggregate_instance_extra_specs:opt2': '2',
        }
        self._do_test_aggregate_filter_extra_specs(especs, passes=True)

    def test_aggregate_filter_passes_extra_specs_simple_comma(self, agg_mock):
        agg_mock.return_value = {'opt1': set(['1', '3']), 'opt2': set(['2'])}
        especs = {
            # Un-scoped extra spec
            'opt1': '1',
            # Scoped extra spec that applies to this filter
            'aggregate_instance_extra_specs:opt1': '3',
        }
        self._do_test_aggregate_filter_extra_specs(especs, passes=True)

    def test_aggregate_filter_passes_with_key_same_as_scope(self, agg_mock):
        agg_mock.return_value = {'aggregate_instance_extra_specs': set(['1'])}
        especs = {
            # Un-scoped extra spec, make sure we don't blow up if it
            # happens to match our scope.
            'aggregate_instance_extra_specs': '1',
        }
        self._do_test_aggregate_filter_extra_specs(especs, passes=True)

    def test_aggregate_filter_fails_extra_specs_simple(self, agg_mock):
        agg_mock.return_value = {'opt1': set(['1']), 'opt2': set(['2'])}
        especs = {
            'opt1': '1',
            'opt2': '222'
        }
        self._do_test_aggregate_filter_extra_specs(especs, passes=False)
