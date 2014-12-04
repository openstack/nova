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

from nova.scheduler.filters import aggregate_multitenancy_isolation as ami
from nova import test
from nova.tests.unit.scheduler import fakes


@mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
class TestAggregateMultitenancyIsolationFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestAggregateMultitenancyIsolationFilter, self).setUp()
        self.filt_cls = ami.AggregateMultiTenancyIsolation()

    def test_aggregate_multi_tenancy_isolation_with_meta_passes(self,
            agg_mock):
        agg_mock.return_value = {'filter_tenant_id': 'my_tenantid'}
        filter_properties = {'context': mock.sentinel.ctx,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_aggregate_multi_tenancy_isolation_fails(self, agg_mock):
        agg_mock.return_value = {'filter_tenant_id': 'other_tenantid'}
        filter_properties = {'context': mock.sentinel.ctx,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_aggregate_multi_tenancy_isolation_no_meta_passes(self, agg_mock):
        agg_mock.return_value = {}
        filter_properties = {'context': mock.sentinel.ctx,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
