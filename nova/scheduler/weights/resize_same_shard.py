# Copyright (c) 2022 SAP
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
"""
Prefer resize to same shard weigher. Resizing an instance gives the current
shard aggregate a higher priority.

This weigher ignores any instances which are:
 * new instances (or unshelving)
 * not resizing (a.k.a. migrating or rebuilding)
"""
from oslo_log import log as logging

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class PreferSameShardOnResizeWeigher(weights.BaseHostWeigher):
    minval = 0
    _SHARD_PREFIX = 'vc-'

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'prefer_same_host_resize_weight_multiplier',
            CONF.filter_scheduler.prefer_same_shard_resize_weight_multiplier)

    def _weigh_object(self, host_state, request_spec):
        """Return 1 for about-to-be-resized instances where the shard is the
        instance's current shard. Return 0 otherwise.
        """
        if not utils.request_is_resize(request_spec):
            return 0.0

        host_shard_aggrs = [aggr for aggr in host_state.aggregates
                            if aggr.name.startswith(self._SHARD_PREFIX)]
        if not host_shard_aggrs:
            LOG.warning('%(host_state)s is not in an aggregate starting with '
                        '%(shard_prefix)s.',
                        {'host_state': host_state,
                         'shard_prefix': self._SHARD_PREFIX})
            return 0.0

        if len(host_shard_aggrs) > 1:
            LOG.warning('More than one host aggregates found for '
                        'host %(host)s, selecting first.',
                        {'host': host_state.host})
        host_shard_aggr = host_shard_aggrs[0]

        instance_host = request_spec.get_scheduler_hint('source_host')
        if instance_host in host_shard_aggr.hosts:
            return 1.0
        return 0.0
