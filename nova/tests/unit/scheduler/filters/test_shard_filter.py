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

from unittest import mock

import nova.conf
from nova import objects
from nova.scheduler.filters import shard_filter
from nova import test
from nova.tests.unit.scheduler import fakes

CONF = nova.conf.CONF


class TestShardFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestShardFilter, self).setUp()
        self.filt_cls = shard_filter.ShardFilter()
        self.filt_cls._PROJECT_TAG_CACHE = {
            'foo': ['vc-a-0', 'vc-b-0'],
            'last_modified': time.time()
        }

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_cache_timeout(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_TAG_CACHE = {
                'foo': ['vc-a-1']
            }
        mock_update_cache.side_effect = set_cache

        project_id = 'foo'
        mod = time.time() - self.filt_cls._PROJECT_TAG_CACHE_RETENTION_TIME

        self.assertEqual(self.filt_cls._get_shards(project_id),
                                                   ['vc-a-0', 'vc-b-0'])

        self.filt_cls._PROJECT_TAG_CACHE['last_modified'] = mod
        self.assertEqual(self.filt_cls._get_shards(project_id), ['vc-a-1'])

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_project_not_included(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_TAG_CACHE = {
                'bar': ['vc-a-1', 'vc-b-0']
            }
        mock_update_cache.side_effect = set_cache

        self.assertEqual(self.filt_cls._get_shards('bar'),
                         ['vc-a-1', 'vc-b-0'])
        mock_update_cache.assert_called_once()

    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_baremetal_passes(self, agg_mock):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs=extra_specs))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_project_not_found(self, agg_mock, mock_update_cache):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='bar',
            flavor=objects.Flavor(extra_specs={}))
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_shard_project_no_shards(self, agg_mock):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.filt_cls._PROJECT_TAG_CACHE['foo'] = []
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
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_shard_match_host_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_shard_do_not_match_host_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-1', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_has_multiple_shards_per_az(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=1, name='vc-a-1', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        self.filt_cls._PROJECT_TAG_CACHE['foo'] = ['vc-a-0', 'vc-a-1',
                                                     'vc-b-0']
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_has_multiple_shards_per_az_resize_same_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1',
                                                                 'host2']),
                objects.Aggregate(id=1, name='vc-a-1', hosts=['host1',
                                                              'host2'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}),
            scheduler_hints=dict(_nova_check_type=['resize'],
                                 source_host=['host2']))

        self.filt_cls._PROJECT_TAG_CACHE['foo'] = ['vc-a-0', 'vc-a-1',
                                                     'vc-b-0']
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_has_multiple_shards_per_az_resize_other_shard(self):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1',
                                                                 'host2']),
                objects.Aggregate(id=1, name='vc-a-1', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}),
            scheduler_hints=dict(_nova_check_type=['resize'],
                                 source_host=['host2']))

        self.filt_cls._PROJECT_TAG_CACHE['foo'] = ['vc-a-0', 'vc-a-1',
                                                     'vc-b-0']
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_has_sharding_enabled_any_host_passes(self):
        self.filt_cls._PROJECT_TAG_CACHE['baz'] = ['sharding_enabled']
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                 objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='baz',
            flavor=objects.Flavor(extra_specs={}))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_shard_project_has_sharding_enabled_and_single_shards(self):
        self.filt_cls._PROJECT_TAG_CACHE['baz'] = ['sharding_enabled',
                                                     'vc-a-1']
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                 objects.Aggregate(id=1, name='vc-a-0', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='baz',
            flavor=objects.Flavor(extra_specs={}))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.shard_filter.LOG')
    @mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
    def test_log_level_for_missing_vc_aggregate(self, agg_mock, log_mock):
        host = fakes.FakeHostState('host1', 'compute', {})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs={}))

        agg_mock.return_value = {}

        # For ironic hosts we log debug
        log_mock.debug = mock.Mock()
        log_mock.error = mock.Mock()
        host.hypervisor_type = 'ironic'
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        log_mock.debug.assert_called_once_with(mock.ANY, mock.ANY)
        log_mock.error.assert_not_called()

        # For other hosts we log error
        log_mock.debug = mock.Mock()
        log_mock.error = mock.Mock()
        host.hypervisor_type = 'Some HV'
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        log_mock.error.assert_called_once_with(mock.ANY, mock.ANY)
        log_mock.debug.assert_not_called()

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_non_vmware_spec(self, mock_is_non_vmware_spec):
        host = mock.sentinel.host
        spec_obj = mock.sentinel.spec_obj

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        mock_is_non_vmware_spec.assert_called_once_with(spec_obj)

    def test_ignores_hana_by_trait(self):
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}
        self._shard_filter_ignoring_hana(True, extra_specs)

    def test_ignores_hana_by_memory(self):
        CONF.set_override('bigvm_mb', 8192)
        CONF.set_override('hana_detection_strategy', 'memory_mb',
                          'filter_scheduler')
        extra_specs = {}
        self._shard_filter_ignoring_hana(True,
                                         extra_specs=extra_specs,
                                         memory_mb=8192)

    def test_sharding_ignore_hana_config(self):
        CONF.set_override('sharding_ignore_hana', False, 'filter_scheduler')
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}
        self._shard_filter_ignoring_hana(False,
                                         extra_specs=extra_specs)

    def test_use_individual_shard_tags_hana_tag(self):
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}
        tag = 'use_individual_shard_tags_hana'
        self._shard_filter_ignoring_hana(False,
                                         extra_specs=extra_specs,
                                         project_tag=tag)

    def test_allow_hana_by_trait_forbidden(self):
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'forbidden'}
        self._shard_filter_ignoring_hana(False, extra_specs)

    def test_allow_hana_by_memory(self):
        CONF.set_override('bigvm_mb', 8192)
        CONF.set_override('hana_detection_strategy', 'memory_mb',
                          'filter_scheduler')
        extra_specs = {}
        self._shard_filter_ignoring_hana(False,
                                         extra_specs=extra_specs,
                                         memory_mb=8191)

    def _shard_filter_ignoring_hana(self, expect_to_ignore, extra_specs=None,
                                    project_tag=None, memory_mb=4096):
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1',
                                                                 'host2']),
                objects.Aggregate(id=1, name='vc-a-1', hosts=['host1'])]

        host_allow = fakes.FakeHostState(
            'host1', 'compute', {'aggregates': aggs})
        host_forbid = fakes.FakeHostState(
            'host2', 'compute', {'aggregates': aggs[:1]})

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id='foo',
            flavor=objects.Flavor(extra_specs=extra_specs,
                                  memory_mb=memory_mb))

        self.filt_cls._PROJECT_TAG_CACHE['foo'] = ['vc-a-0', 'vc-a-1',
                                                   'vc-b-0']
        if project_tag:
            self.filt_cls._PROJECT_TAG_CACHE['foo'].append(project_tag)
        result = list(self.filt_cls.filter_all(
            [host_allow, host_forbid], spec_obj))
        if expect_to_ignore:
            self.assertEqual(result, [host_allow, host_forbid])
        else:
            self.assertEqual(result, [host_allow])
