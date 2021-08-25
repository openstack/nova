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

from nova import context
from nova.scheduler.client import report


class HypervisorSizeMixin(object):

    _HV_SIZE_CACHE_RETENTION_TIME = 10 * 60
    _HV_SIZE_CACHE = {}

    def _get_hv_size(self, host_state):
        # expire the cache 10min after last write
        time_diff = time.time() - self._HV_SIZE_CACHE.get('last_modified', 0)
        if time_diff > self._HV_SIZE_CACHE_RETENTION_TIME:
            self._HV_SIZE_CACHE = {}

        if host_state.uuid not in self._HV_SIZE_CACHE:
            placement_client = report.SchedulerReportClient()
            elevated = context.get_admin_context()
            res = placement_client._get_inventory(elevated, host_state.uuid)
            if not res:
                return None
            inventories = res.get('inventories', {})
            hv_size_mb = inventories.get('MEMORY_MB', {}).get('max_unit')
            self._HV_SIZE_CACHE[host_state.uuid] = hv_size_mb

            self._HV_SIZE_CACHE['last_modified'] = time.time()

        return self._HV_SIZE_CACHE[host_state.uuid]
