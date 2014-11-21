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

from oslo.config import cfg

from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)

disk_allocation_ratio_opt = cfg.FloatOpt("disk_allocation_ratio", default=1.0,
                         help="Virtual disk to physical disk allocation ratio")

CONF = cfg.CONF
CONF.register_opt(disk_allocation_ratio_opt)


class DiskFilter(filters.BaseHostFilter):
    """Disk Filter with over subscription flag."""

    def _get_disk_allocation_ratio(self, host_state, filter_properties):
        return CONF.disk_allocation_ratio

    def host_passes(self, host_state, filter_properties):
        """Filter based on disk usage."""
        instance_type = filter_properties.get('instance_type')
        requested_disk = (1024 * (instance_type['root_gb'] +
                                 instance_type['ephemeral_gb']) +
                         instance_type['swap'])

        free_disk_mb = host_state.free_disk_mb
        total_usable_disk_mb = host_state.total_usable_disk_gb * 1024

        disk_allocation_ratio = self._get_disk_allocation_ratio(
            host_state, filter_properties)

        disk_mb_limit = total_usable_disk_mb * disk_allocation_ratio
        used_disk_mb = total_usable_disk_mb - free_disk_mb
        usable_disk_mb = disk_mb_limit - used_disk_mb

        if not usable_disk_mb >= requested_disk:
            LOG.debug("%(host_state)s does not have %(requested_disk)s MB "
                    "usable disk, it only has %(usable_disk_mb)s MB usable "
                    "disk.", {'host_state': host_state,
                               'requested_disk': requested_disk,
                               'usable_disk_mb': usable_disk_mb})
            return False

        disk_gb_limit = disk_mb_limit / 1024
        host_state.limits['disk_gb'] = disk_gb_limit
        return True


class AggregateDiskFilter(DiskFilter):
    """AggregateDiskFilter with per-aggregate disk allocation ratio flag.

    Fall back to global disk_allocation_ratio if no per-aggregate setting
    found.
    """

    def _get_disk_allocation_ratio(self, host_state, filter_properties):
        # TODO(uni): DB query in filter is a performance hit, especially for
        # system with lots of hosts. Will need a general solution here to fix
        # all filters with aggregate DB call things.
        aggregate_vals = utils.aggregate_values_from_db(
            filter_properties['context'],
            host_state.host,
            'disk_allocation_ratio')
        try:
            ratio = utils.validate_num_values(
                aggregate_vals, CONF.disk_allocation_ratio, cast_to=float)
        except ValueError as e:
            LOG.warning(_LW("Could not decode disk_allocation_ratio: '%s'"), e)
            ratio = CONF.disk_allocation_ratio

        return ratio
