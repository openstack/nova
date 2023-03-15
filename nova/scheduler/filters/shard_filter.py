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
from oslo_log import log as logging

import nova.conf
from nova.scheduler import filters
from nova.scheduler.mixins import ProjectTagMixin
from nova.scheduler import utils
from nova import utils as nova_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class ShardFilter(filters.BaseHostFilter, ProjectTagMixin):
    """Filter hosts based on the vcenter-shard configured in their aggregate
    and the vcenter-shards configured in the project's tags in keystone. They
    have to overlap for a host to pass this filter.

    Alternatively the project may have the "sharding_enabled" tag set, which
    enables the project for hosts in all shards.
    """

    _ALL_SHARDS = "sharding_enabled"
    _SHARD_PREFIX = 'vc-'
    _PROJECT_TAG_TAGS = [_ALL_SHARDS]
    _PROJECT_TAG_PREFIX = _SHARD_PREFIX

    def _get_shards(self, project_id):
        """Return a set of shards for a project or None"""
        # NOTE(jkulik): We wrap _get_tags() here to change the name to
        # _get_shards() so it's clear what we return
        return self._get_tags(project_id)

    def host_passes(self, host_state, spec_obj):
        # Only VMware
        if utils.is_non_vmware_spec(spec_obj):
            return True

        host_shard_aggrs = [aggr for aggr in host_state.aggregates
                            if aggr.name.startswith(self._SHARD_PREFIX)]

        host_shard_names = set(aggr.name for aggr in host_shard_aggrs)
        if not host_shard_names:
            log_method = (LOG.debug if nova_utils.is_baremetal_host(host_state)
                          else LOG.error)
            log_method('%(host_state)s is not in an aggregate starting with '
                       '%(shard_prefix)s.',
                       {'host_state': host_state,
                        'shard_prefix': self._SHARD_PREFIX})
            return False

        project_id = spec_obj.project_id

        shards = self._get_shards(project_id)
        if shards is None:
            LOG.error('Failure retrieving shards for project %(project_id)s.',
                      {'project_id': project_id})
            return False

        if not len(shards):
            LOG.error('Project %(project_id)s is not assigned to any shard.',
                      {'project_id': project_id})
            return False

        if self._ALL_SHARDS in shards:
            LOG.debug('project enabled for all shards %(project_shards)s.',
                      {'project_shards': shards})
            return True
        elif host_shard_names & set(shards):
            LOG.debug('%(host_state)s shard %(host_shard)s found in project '
                      'shards %(project_shards)s.',
                      {'host_state': host_state,
                       'host_shard': host_shard_names,
                       'project_shards': shards})
            return True
        else:
            LOG.debug('%(host_state)s shard %(host_shard)s not found in '
                      'project shards %(project_shards)s.',
                      {'host_state': host_state,
                       'host_shard': host_shard_names,
                       'project_shards': shards})
            return False
