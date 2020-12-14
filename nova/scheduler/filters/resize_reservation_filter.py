# Copyright (c) 2020 SAP SE
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
from nova.scheduler import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class ResizeReservedRAMFilter(filters.BaseHostFilter):
    """Only return hosts for either resize or sufficient available RAM."""

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, request_spec):
        if utils.request_is_resize(request_spec):
            return True

        total_usable_ram_mb = host_state.total_usable_ram_mb
        ram_allocation_ratio = host_state.ram_allocation_ratio
        free_ram_mb = host_state.free_ram_mb
        memory_mb_limit = total_usable_ram_mb * ram_allocation_ratio
        used_ram_mb = total_usable_ram_mb - free_ram_mb
        wanted_ram_mb = used_ram_mb + request_spec.memory_mb
        wanted_ram_percent = wanted_ram_mb / memory_mb_limit * 100
        if 100 - wanted_ram_percent < \
                CONF.filter_scheduler.resize_reserved_ram_percent:
            LOG.info(
                "Spawning on host (%(host_state)s) would use part of "
                "the memory reserved for resizes (%(ram_percent)s%%).",
                {"host_state": host_state, "ram_percent": wanted_ram_percent}
            )
            return False
        return True
