# Copyright 2024 SAP
# All Rights Reserved.
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
from unittest import mock

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import aggregate_multitenancy_isolation as a_m_i
from nova import test
from nova.tests.unit.scheduler import fakes


@mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
class TestAggregateMultitenancyIsolationWeigher(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [a_m_i.AggregateMultiTenancyIsolation()]

        # NOTE(jkulik): We need at least 2 hosts for the HostWeightHandler to
        # do anything. They also need to return different weights or we just
        # see 0 all the time. The multiplier is applied after the
        # normalization.
        self.hosts = [
            fakes.FakeHostState('host1', 'compute', {}),
            fakes.FakeHostState('host2', 'compute', {})]

    def test_no_metadata_zero_weight(self, agg_mock):
        """no metadata, no weight"""
        agg_mock.side_effect = [{}, {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(0.0, weighed_hosts[0].weight)

    def test_not_our_key_zero_weight(self, agg_mock):
        """not our key in metadata, no weight"""
        agg_mock.side_effect = [{'the_key': 'the_value'}, {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(0.0, weighed_hosts[0].weight)

    def test_not_in_the_value_zero_weight(self, agg_mock):
        """our project is not in the metadata value, no weight"""
        agg_mock.side_effect = [
            {'filter_tenant_id': {'one_project', 'another_project'}},
            {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(0.0, weighed_hosts[0].weight)

    def test_in_the_value(self, agg_mock):
        """our project is in the metadata value, we have weight"""
        agg_mock.side_effect = [
            {'filter_tenant_id': {'one_project', 'another_project',
                                 'my_tenantid'}},
            {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(1.0, weighed_hosts[0].weight)

    def test_multiplier(self, agg_mock):
        """our project is in the metadata value, we have weight multiplied"""
        self.flags(aggregate_multi_tenancy_isolation_weight_multiplier=5.0,
                   group='filter_scheduler')

        agg_mock.side_effect = [
            {'filter_tenant_id': {'one_project', 'another_project',
                                 'my_tenantid'}},
            {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(5.0, weighed_hosts[0].weight)

    def test_disabled(self, agg_mock):
        """our project is in the metadata value, but multplier disables it"""
        self.flags(aggregate_multi_tenancy_isolation_weight_multiplier=0.0,
                   group='filter_scheduler')

        agg_mock.side_effect = [
            {'filter_tenant_id': {'one_project', 'another_project',
                                 'my_tenantid'}},
            {}]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='my_tenantid')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, spec_obj)
        self.assertEqual(0.0, weighed_hosts[0].weight)
