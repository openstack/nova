# Copyright (c) 2011 OpenStack Foundation
# Copyright (c) 2012 Cloudscaling
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

from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)


class AggregateRamFilter(filters.BaseHostFilter):
    """DEPRECATED: AggregateRamFilter with per-aggregate ram subscription flag.

    Fall back to global ram_allocation_ratio if no per-aggregate setting found.
    """

    RUN_ON_REBUILD = False

    def __init__(self):
        super(AggregateRamFilter, self).__init__()
        LOG.warning('The AggregateRamFilter is deprecated since the 20.0.0 '
                    'Train release. MEMORY_MB filtering is performed natively '
                    'using the Placement service when using the '
                    'filter_scheduler driver. Operators should define ram '
                    'allocation ratios either per host in the nova.conf '
                    'or via the placement API.')

    def _get_ram_allocation_ratio(self, host_state, spec_obj):
        aggregate_vals = utils.aggregate_values_from_key(
            host_state,
            'ram_allocation_ratio')

        try:
            ratio = utils.validate_num_values(
                aggregate_vals, host_state.ram_allocation_ratio, cast_to=float)
        except ValueError as e:
            LOG.warning("Could not decode ram_allocation_ratio: '%s'", e)
            ratio = host_state.ram_allocation_ratio

        return ratio

    def host_passes(self, host_state, spec_obj):
        """Only return hosts with sufficient available RAM."""
        requested_ram = spec_obj.memory_mb
        free_ram_mb = host_state.free_ram_mb
        total_usable_ram_mb = host_state.total_usable_ram_mb

        # Do not allow an instance to overcommit against itself, only against
        # other instances.
        if not total_usable_ram_mb >= requested_ram:
            LOG.debug("%(host_state)s does not have %(requested_ram)s MB "
                      "usable ram before overcommit, it only has "
                      "%(usable_ram)s MB.",
                      {'host_state': host_state,
                       'requested_ram': requested_ram,
                       'usable_ram': total_usable_ram_mb})
            return False

        ram_allocation_ratio = self._get_ram_allocation_ratio(host_state,
                                                              spec_obj)

        memory_mb_limit = total_usable_ram_mb * ram_allocation_ratio
        used_ram_mb = total_usable_ram_mb - free_ram_mb
        usable_ram = memory_mb_limit - used_ram_mb
        if not usable_ram >= requested_ram:
            LOG.debug("%(host_state)s does not have %(requested_ram)s MB "
                      "usable ram, it only has %(usable_ram)s MB usable ram.",
                      {'host_state': host_state,
                       'requested_ram': requested_ram,
                       'usable_ram': usable_ram})
            return False

        # save oversubscription limit for compute node to test against:
        host_state.limits['memory_mb'] = memory_mb_limit
        return True
