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
from oslo_cache.backends.dictionary import DictCacheBackend
from oslo_cache import core as cache_core
from oslo_log import log as logging

from nova import context
from nova.scheduler.client import report

LOG = logging.getLogger(__name__)


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
