# Copyright (c) 2019 SAP SE
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
import time

import mock

from nova import objects
from nova.scheduler.filters import shard_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestShardFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestShardFilter, self).setUp()
        self.filt_cls = shard_filter.ShardFilter()
        self.filt_cls._PROJECT_SHARD_CACHE = {
            'foo': ['vc-a-0', 'vc-b-0'],
            'last_modified': time.time()
        }

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_cache_timeout(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_SHARD_CACHE = {
                'foo': ['vc-a-1']
            }
        mock_update_cache.side_effect = set_cache

        project_id = 'foo'
        mod = time.time() - self.filt_cls._PROJECT_SHARD_CACHE_RETENTION_TIME

        self.assertEqual(self.filt_cls._get_shards(project_id),
                                                   ['vc-a-0', 'vc-b-0'])

        self.filt_cls._PROJECT_SHARD_CACHE['last_modified'] = mod
        self.assertEqual(self.filt_cls._get_shards(project_id), ['vc-a-1'])

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_project_not_included(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_SHARD_CACHE = {
                'bar': ['vc-a-1', 'vc-b-0']
            }
        mock_update_cache.side_effect = set_cache

        self.assertEqual(self.filt_cls._get_shards('bar'),
                         ['vc-a-1', 'vc-b-0'])
        mock_update_cache.assert_called_once()

    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_baremetal_passes(self, agg_mock):
        host = fakes.FakeHostState('host1', 'compute', {})
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs=extra_specs))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_project_not_found(self, agg_mock, mock_update_cache):
        host = fakes.FakeHostState('host1', 'compute', {})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='bar',
            flavor=objects.Flavor(extra_specs={}))
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_project_no_shards(self, agg_mock):
        host = fakes.FakeHostState('host1', 'compute', {})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.filt_cls._PROJECT_SHARD_CACHE['foo'] = []
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_host_no_shard_aggregate(self, agg_mock):
        host = fakes.FakeHostState('host1', 'compute', {})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        agg_mock.return_value = {}
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_host_no_shards_in_aggregate(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a')]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_shard_match_host_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a'),
                objects.Aggregate(id=1, name='vc-a-0')]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_shard_do_not_match_host_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a'),
                objects.Aggregate(id=1, name='vc-a-1')]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
