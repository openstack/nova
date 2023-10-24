# Copyright (c) 2021 SAP SE
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
from oslo_cache.backends.dictionary import DictCacheBackend
from oslo_cache import core as cache_core
from oslo_log import log as logging

import nova.conf
from nova import context
from nova.scheduler.client import report
from nova import utils as nova_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

_SERVICE_AUTH = None


class HypervisorSizeMixin(object):

    _HV_SIZE_CACHE = DictCacheBackend({'expiration_time': 10 * 60})

    def _get_hv_size(self, host_state):
        hv_size_mb = self._HV_SIZE_CACHE.get(host_state.uuid)
        if hv_size_mb != cache_core.NO_VALUE:
            return hv_size_mb

        placement_client = report.SchedulerReportClient()
        elevated = context.get_admin_context()
        res = placement_client._get_inventory(elevated, host_state.uuid)
        if not res:
            return None
        inventories = res.get('inventories', {})
        hv_size_mb = inventories.get('MEMORY_MB', {}).get('max_unit')
        self._HV_SIZE_CACHE.set(host_state.uuid, hv_size_mb)

        return hv_size_mb


class ProjectTagMixin:

    _PROJECT_TAG_CACHE = {}
    _PROJECT_TAG_CACHE_RETENTION_TIME = 10 * 60
    # Optional prefix to filter for in tags to cache. Works in addition to
    # _PROJECT_TAG_TAGS i.e. as an OR
    _PROJECT_TAG_PREFIX = None
    # Optional explicit list of tags to cache. Works in addition to
    # _PROJECT_TAG_PREFIX i.e. as an OR
    _PROJECT_TAG_TAGS = None

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
                tags = []
                for t in project['tags']:
                    if self._PROJECT_TAG_TAGS and t in self._PROJECT_TAG_TAGS:
                        tags.append(t)
                    if (self._PROJECT_TAG_PREFIX and
                            t.startswith(self._PROJECT_TAG_PREFIX)):
                        tags.append(t)
                self._PROJECT_TAG_CACHE[project_id] = tags

            url = data['links']['next']

        self._PROJECT_TAG_CACHE['last_modified'] = time.time()

    def _get_tags(self, project_id):
        """Return a list of tags for a project or None

        This should be quite fast except if we update the cache. Since we only
        need one thread updating the cache, we let the other threads wait here.
        """
        # we inline the function to customize the key with the name of the
        # class we're used as mixin in
        key = f"update-project-tag-cache-{self.__class__.__name__}"

        @nova_utils.synchronized(key)
        def _synchronized_get_tags(project_id):
            # expire the cache 10min after last write
            last_modified = self._PROJECT_TAG_CACHE.get('last_modified', 0)
            time_diff = time.time() - last_modified
            if time_diff > self._PROJECT_TAG_CACHE_RETENTION_TIME:
                self._PROJECT_TAG_CACHE = {}

            if project_id not in self._PROJECT_TAG_CACHE:
                self._update_cache()

            return self._PROJECT_TAG_CACHE.get(project_id)

        return _synchronized_get_tags(project_id)
