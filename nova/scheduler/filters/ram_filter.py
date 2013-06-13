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

from oslo.config import cfg

from nova import db
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)

ram_allocation_ratio_opt = cfg.FloatOpt('ram_allocation_ratio',
        default=1.5,
        help='Virtual ram to physical ram allocation ratio which affects '
             'all ram filters. This configuration specifies a global ratio '
             'for RamFilter. For AggregateRamFilter, it will fall back to '
             'this configuration value if no per-aggregate setting found.')

CONF = cfg.CONF
CONF.register_opt(ram_allocation_ratio_opt)


class BaseRamFilter(filters.BaseHostFilter):

    def _get_ram_allocation_ratio(self, host_state, filter_properties):
        raise NotImplementedError

    def host_passes(self, host_state, filter_properties):
        """Only return hosts with sufficient available RAM."""
        instance_type = filter_properties.get('instance_type')
        requested_ram = instance_type['memory_mb']
        free_ram_mb = host_state.free_ram_mb
        total_usable_ram_mb = host_state.total_usable_ram_mb

        ram_allocation_ratio = self._get_ram_allocation_ratio(host_state,
                                                          filter_properties)

        memory_mb_limit = total_usable_ram_mb * ram_allocation_ratio
        used_ram_mb = total_usable_ram_mb - free_ram_mb
        usable_ram = memory_mb_limit - used_ram_mb
        if not usable_ram >= requested_ram:
            LOG.debug(_("%(host_state)s does not have %(requested_ram)s MB "
                    "usable ram, it only has %(usable_ram)s MB usable ram."),
                    {'host_state': host_state,
                     'requested_ram': requested_ram,
                     'usable_ram': usable_ram})
            return False

        # save oversubscription limit for compute node to test against:
        host_state.limits['memory_mb'] = memory_mb_limit
        return True


class RamFilter(BaseRamFilter):
    """Ram Filter with over subscription flag."""

    def _get_ram_allocation_ratio(self, host_state, filter_properties):
        return CONF.ram_allocation_ratio


class AggregateRamFilter(BaseRamFilter):
    """AggregateRamFilter with per-aggregate ram subscription flag.

    Fall back to global ram_allocation_ratio if no per-aggregate setting found.
    """

    def _get_ram_allocation_ratio(self, host_state, filter_properties):
        context = filter_properties['context'].elevated()
        # TODO(uni): DB query in filter is a performance hit, especially for
        # system with lots of hosts. Will need a general solution here to fix
        # all filters with aggregate DB call things.
        metadata = db.aggregate_metadata_get_by_host(
                     context, host_state.host, key='ram_allocation_ratio')
        aggregate_vals = metadata.get('ram_allocation_ratio', set())
        num_values = len(aggregate_vals)

        if num_values == 0:
            return CONF.ram_allocation_ratio

        if num_values > 1:
            LOG.warning(_("%(num_values)d ratio values found, "
                          "of which the minimum value will be used."),
                         {'num_values': num_values})

        try:
            ratio = float(min(aggregate_vals))
        except ValueError as e:
            LOG.warning(_("Could not decode ram_allocation_ratio: '%s'"), e)
            ratio = CONF.ram_allocation_ratio

        return ratio
