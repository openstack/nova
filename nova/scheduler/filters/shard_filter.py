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

from keystoneauth1 import exceptions as kse
from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging

import nova.conf
from nova.scheduler import filters
from nova import utils as nova_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

_SERVICE_AUTH = None


class ShardFilter(filters.BaseHostFilter):
    """Filter hosts based on the vcenter-shard configured in their aggregate
    and the vcenter-shards configured in the project's tags in keystone. They
    have to overlap for a host to pass this filter.

    Alternatively the project may have the "sharding_enabled" tag set, which
    enables the project for hosts in all shards.
    """

    _PROJECT_SHARD_CACHE = {}
    _PROJECT_SHARD_CACHE_RETENTION_TIME = 10 * 60
    _SHARD_PREFIX = 'vc-'
    _ALL_SHARDS = "sharding_enabled"

    def _update_cache(self):
        """Ask keystone for the list of projects to save the interesting tags
        of each project in the cache
        """
        global _SERVICE_AUTH

        if _SERVICE_AUTH is None:
            _SERVICE_AUTH = ks_loading.load_auth_from_conf_options(
                                CONF,
                                group=
                                nova.conf.service_token.SERVICE_USER_GROUP)
            if _SERVICE_AUTH is None:
                # This indicates a misconfiguration so log a warning and
                # return the user_auth.
                LOG.error('Unable to load auth from [service_user] '
                          'configuration. Ensure "auth_type" is set.')
                return

        adap = nova_utils.get_ksa_adapter(
            'identity', ksa_auth=_SERVICE_AUTH,
            min_version=(3, 0), max_version=(3, 'latest'))

        url = '/projects'
        while url:
            try:
                resp = adap.get(url, raise_exc=False)
            except kse.EndpointNotFound:
                LOG.error(
                    "Keystone identity service version 3.0 was not found. "
                    "This might be because your endpoint points to the v2.0 "
                    "versioned endpoint which is not supported. Please fix "
                    "this.")
                return
            except kse.ClientException:
                LOG.error("Unable to contact keystone to update project tags "
                          "cache")
                return

            resp.raise_for_status()

            data = resp.json()
            for project in data['projects']:
                project_id = project['id']
                shards = [t for t in project['tags']
                          if t.startswith(self._SHARD_PREFIX) or
                          t == self._ALL_SHARDS]
                self._PROJECT_SHARD_CACHE[project_id] = shards

            url = data['links']['next']

        self._PROJECT_SHARD_CACHE['last_modified'] = time.time()

    @nova_utils.synchronized('update-shard-cache')
    def _get_shards(self, project_id):
        """Return a set of shards for a project or None

        This should be quite fast except if we update the cache. Since we only
        need one thread updating the cache, we let the other threads wait here.
        """
        # expire the cache 10min after last write
        last_modified = self._PROJECT_SHARD_CACHE.get('last_modified', 0)
        time_diff = time.time() - last_modified
        if time_diff > self._PROJECT_SHARD_CACHE_RETENTION_TIME:
            self._PROJECT_SHARD_CACHE = {}

        if project_id not in self._PROJECT_SHARD_CACHE:
            self._update_cache()

        return self._PROJECT_SHARD_CACHE.get(project_id)

    def host_passes(self, host_state, spec_obj):
        # ignore baremetal
        if nova_utils.is_baremetal_flavor(spec_obj.flavor):
            return True

        host_shard_aggrs = [aggr for aggr in host_state.aggregates
                            if aggr.name.startswith(self._SHARD_PREFIX)]

        host_shard_names = set(aggr.name for aggr in host_shard_aggrs)
        if not host_shard_names:
            LOG.error('%(host_state)s is not in an aggregate starting with '
                      '%(shard_prefix)s.',
                      {'host_state': host_state,
                       'shard_prefix': self._SHARD_PREFIX})
            return False

        # forbid changing the shard of an instance
        instance_host = spec_obj.get_scheduler_hint('source_host')
        host_shard_hosts = set()
        host_shard_hosts.update(*(aggr.hosts for aggr in host_shard_aggrs))
        if instance_host and instance_host not in host_shard_hosts:
            LOG.debug('%(host_state)s is in another shard than the '
                      'instance\'s %(instance_host)s',
                      {'host_state': host_state,
                       'instance_host': instance_host})
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
