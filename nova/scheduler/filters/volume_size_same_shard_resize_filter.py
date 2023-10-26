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
from oslo_log import log as logging

import nova.conf
from nova.scheduler import filters
from nova.scheduler.mixins import ProjectTagMixin
from nova.scheduler import utils
from nova import utils as nova_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class VolumeSizeSameShardResizeFilter(filters.BaseHostFilter, ProjectTagMixin):
    """Filter out other shards on resize with too big volumes

    A project can opt in to this by setting the appropriate tag (see
    _TAG below).
    The sum of the sizes of the volumes attached to the VM trigger the
    behavior. It's configured below in _VOLUME_SIZE_SUM.
    """
    _TAG = 'restrict-resize-by-volume-size'
    _PROJECT_TAG_TAGS = [_TAG]
    # sum of the volumes size >= we do not allow a host as resize target
    _VOLUME_SIZE_SUM = \
        CONF.filter_scheduler.volume_size_same_shard_resize_filter_sum
    # prefix of the aggregate names that make them a shard
    _SHARD_PREFIX = 'vc-'

    def _has_tag(self, project_id):
        """Return boolean if the project has our tag set"""
        return self._TAG in self._get_tags(project_id)

    def host_passes(self, host_state, request_spec):
        # Only VMware
        if utils.is_non_vmware_spec(request_spec):
            return True

        if not utils.request_is_resize(request_spec):
            return True

        project_id = request_spec.project_id
        if not self._has_tag(project_id):
            LOG.debug('%(host_state)s allowed, because project %(project_id)s '
                      'did not set %(tag)s',
                      {'host_state': host_state, 'project_id': project_id,
                       'tag': self._TAG})
            return True

        if ('scheduler_hints' not in request_spec or
                'volume_sizes' not in request_spec.scheduler_hints):
            LOG.error('Resize without "volume_sizes" scheduler-hint')
            return False

        volume_sizes = request_spec.scheduler_hints['volume_sizes']
        if not volume_sizes:
            LOG.debug('%(host_state)s allowed, because the instance has no '
                      'volumes', {'host_state': host_state})
            return True

        # NOTE(jkulik): scheduler_hints are of type DictOfListOfStringsField
        # so we need to convert them to int to sum them up
        volume_size_sum = 0
        for s in volume_sizes:
            if not s:
                continue
            try:
                volume_size_sum += int(s)
            except ValueError:
                pass
        if volume_size_sum < self._VOLUME_SIZE_SUM:
            LOG.debug('%(host_state)s allowed, because the instances has a '
                      'sum of %(sum)s GiB of volumes and we allow '
                      '%(configured_sum)s GiB',
                      {'host_state': host_state, 'sum': volume_size_sum,
                       'configured_sum': self._VOLUME_SIZE_SUM})
            return True

        host_shard_aggrs = [aggr for aggr in host_state.aggregates
                            if aggr.name.startswith(self._SHARD_PREFIX)]
        if not host_shard_aggrs:
            log_method = (LOG.debug if nova_utils.is_baremetal_host(host_state)
                          else LOG.error)
            log_method('%(host_state)s is not in an aggregate starting with '
                       '%(shard_prefix)s',
                       {'host_state': host_state,
                        'shard_prefix': self._SHARD_PREFIX})
            return False

        if len(host_shard_aggrs) > 1:
            LOG.error('More than one host aggregates found for '
                      'host %(host)s: %(aggrs)s',
                      {'host': host_state.host,
                       'aggrs': ', '.join([a.name for a in host_shard_aggrs])})
        host_shard_aggr = host_shard_aggrs[0]

        instance_host = request_spec.get_scheduler_hint('source_host')
        if instance_host in host_shard_aggr.hosts:
            LOG.debug('%(host_state)s allowed, as it has the same shard '
                      '%(shard_name)s as the source host %(source_host)s',
                      {'host_state': host_state,
                       'shard_name': host_shard_aggr.name,
                       'source_host': instance_host})
            return True

        LOG.debug('%(host_state)s not allowed, as it has another shard '
                  '%(shard_name)s as the source host %(source_host)s and the '
                  'instance has %(sum)s GiB of volumes which is >= the '
                  'configured %(configured_sum)s',
                  {'host_state': host_state,
                   'shard_name': host_shard_aggr.name,
                   'source_host': instance_host,
                   'sum': volume_size_sum,
                   'configured_sum': self._VOLUME_SIZE_SUM
                   })
        return False
