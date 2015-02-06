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

from oslo_config import cfg

from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)

max_instances_per_host_opt = cfg.IntOpt("max_instances_per_host",
        default=50,
        help="Ignore hosts that have too many instances")

CONF = cfg.CONF
CONF.register_opt(max_instances_per_host_opt)


class NumInstancesFilter(filters.BaseHostFilter):
    """Filter out hosts with too many instances."""

    def _get_max_instances_per_host(self, host_state, filter_properties):
        return CONF.max_instances_per_host

    def host_passes(self, host_state, filter_properties):
        num_instances = host_state.num_instances
        max_instances = self._get_max_instances_per_host(
            host_state, filter_properties)
        passes = num_instances < max_instances
        if not passes:
            LOG.debug("%(host_state)s fails num_instances check: Max "
                        "instances per host is set to %(max_instances)s",
                        {'host_state': host_state,
                         'max_instances': max_instances})
        return passes


class AggregateNumInstancesFilter(NumInstancesFilter):
    """AggregateNumInstancesFilter with per-aggregate the max num instances.

    Fall back to global max_num_instances_per_host if no per-aggregate setting
    found.
    """

    def _get_max_instances_per_host(self, host_state, filter_properties):
        # TODO(uni): DB query in filter is a performance hit, especially for
        # system with lots of hosts. Will need a general solutnumn here to fix
        # all filters with aggregate DB call things.
        aggregate_vals = utils.aggregate_values_from_db(
            filter_properties['context'],
            host_state.host,
            'max_instances_per_host')
        try:
            value = utils.validate_num_values(
                aggregate_vals, CONF.max_instances_per_host, cast_to=int)
        except ValueError as e:
            LOG.warning(_LW("Could not decode max_instances_per_host: '%s'"),
                        e)
            value = CONF.max_instances_per_host

        return value
