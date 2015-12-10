# Copyright (c) 2012 OpenStack Foundation
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
from nova.i18n import _LW
from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class IoOpsFilter(filters.BaseHostFilter):
    """Filter out hosts with too many concurrent I/O operations."""

    def _get_max_io_ops_per_host(self, host_state, spec_obj):
        return CONF.max_io_ops_per_host

    def host_passes(self, host_state, spec_obj):
        """Use information about current vm and task states collected from
        compute node statistics to decide whether to filter.
        """
        num_io_ops = host_state.num_io_ops
        max_io_ops = self._get_max_io_ops_per_host(
            host_state, spec_obj)
        passes = num_io_ops < max_io_ops
        if not passes:
            LOG.debug("%(host_state)s fails I/O ops check: Max IOs per host "
                        "is set to %(max_io_ops)s",
                        {'host_state': host_state,
                         'max_io_ops': max_io_ops})
        return passes


class AggregateIoOpsFilter(IoOpsFilter):
    """AggregateIoOpsFilter with per-aggregate the max io operations.

    Fall back to global max_io_ops_per_host if no per-aggregate setting found.
    """

    def _get_max_io_ops_per_host(self, host_state, spec_obj):
        aggregate_vals = utils.aggregate_values_from_key(
            host_state,
            'max_io_ops_per_host')
        try:
            value = utils.validate_num_values(
                aggregate_vals, CONF.max_io_ops_per_host, cast_to=int)
        except ValueError as e:
            LOG.warning(_LW("Could not decode max_io_ops_per_host: '%s'"), e)
            value = CONF.max_io_ops_per_host

        return value
