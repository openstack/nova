# Copyright (c) 2023 SAP SE
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

from oslo_utils.fixture import uuidsentinel as uuids

from nova import objects
from nova.scheduler.filters import volume_size_same_shard_resize_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestVolumeSizeSameShardResizeFilter(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.filt_cls = (volume_size_same_shard_resize_filter
                         .VolumeSizeSameShardResizeFilter())
        self.filt_cls._PROJECT_TAG_CACHE = {
            uuids.project_with: [self.filt_cls._TAG],
            uuids.project_without: [],
            'last_modified': time.time()
        }
        self.flavor = objects.Flavor(extra_specs={})
        self.spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id=uuids.project_with,
            flavor=self.flavor,
            scheduler_hints=dict(_nova_check_type=['resize'],
                                 source_host=['host2']))

    def test_non_vmware_passes(self):
        """We only need sharding for VMware hypervisors"""
        host = fakes.FakeHostState('host1', 'compute', {})
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id=uuids.project_without,
            flavor=objects.Flavor(extra_specs=extra_specs))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_non_resize_passes(self):
        """The filter should only check resizes"""
        host = fakes.FakeHostState('host1', 'compute', {})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx, project_id=uuids.project_without,
            flavor=self.flavor)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_projects_without_tag_pass(self):
        """we only need to check volumes if the tag is present"""
        host = fakes.FakeHostState('host1', 'compute', {})
        self.spec_obj.project_id = uuids.project_without
        self.assertTrue(self.filt_cls.host_passes(host, self.spec_obj))

    def test_host_without_shard_fails(self):
        """if the host doesn't have an aggregate, we cannot accept it as it
        might be in another shard
        """
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        self.assertFalse(self.filt_cls.host_passes(host, self.spec_obj))

    def test_host_with_multiple_shards_fails(self):
        """we cannot decide whether this will work, so we rather not pass"""
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=2, name='vc-a-1', hosts=['host1']),
                objects.Aggregate(id=3, name='vc-a-2', hosts=['host2'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        self.assertFalse(self.filt_cls.host_passes(host, self.spec_obj))

    def test_scheduler_hints_without_volume_sizes_fails(self):
        """if we did not get the "volume_sizes" key for a resize, we run
        outdated code somewhere and need to bail
        """
        aggs = [objects.Aggregate(id=1, name='some-az-a', hosts=['host1']),
                objects.Aggregate(id=2, name='vc-a-1', hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        self.assertFalse(self.filt_cls.host_passes(host, self.spec_obj))

    def test_volumes_sum_below_threshold_passes(self):
        """if the sum of volume sizes does not reach the threshold, we don't
        have to check shards and can pass
        """
        host = fakes.FakeHostState('host1', 'compute', {})
        self.spec_obj.scheduler_hints['volume_sizes'] = [
            10, self.filt_cls._VOLUME_SIZE_SUM - 11]
        self.assertTrue(self.filt_cls.host_passes(host, self.spec_obj))

    def test_source_host_in_aggregate_passes(self):
        """the host is in the same shard as our source host, which does not
        create any volume migrations
        """
        aggs = [objects.Aggregate(id=1, name='some-az-a',
                                  hosts=['host1', 'host2']),
                objects.Aggregate(id=2, name='vc-a-1',
                                  hosts=['host1', 'host2'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        self.spec_obj.scheduler_hints['volume_sizes'] = [
            10, 5, self.filt_cls._VOLUME_SIZE_SUM - 15]
        self.assertTrue(self.filt_cls.host_passes(host, self.spec_obj))

    def test_source_host_not_in_aggregate_fails(self):
        """the host is in another shard than our source host, which would
        create volume migrations
        """
        aggs = [objects.Aggregate(id=1, name='some-az-a',
                                  hosts=['host1', 'host2']),
                objects.Aggregate(id=2, name='vc-a-1',
                                  hosts=['host1'])]
        host = fakes.FakeHostState('host1', 'compute', {'aggregates': aggs})
        self.spec_obj.scheduler_hints['volume_sizes'] = [
            10, 5, self.filt_cls._VOLUME_SIZE_SUM - 15]
        self.assertFalse(self.filt_cls.host_passes(host, self.spec_obj))
