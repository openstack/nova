# Copyright (c) 2011 OpenStack Foundation
# Copyright (c) 2012 Justin Santa Barbara
#
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

cpu_allocation_ratio_opt = cfg.FloatOpt('cpu_allocation_ratio',
        default=16.0,
        help='Virtual CPU to physical CPU allocation ratio which affects '
             'all CPU filters. This configuration specifies a global ratio '
             'for CoreFilter. For AggregateCoreFilter, it will fall back to '
             'this configuration value if no per-aggregate setting found.')

CONF = cfg.CONF
CONF.register_opt(cpu_allocation_ratio_opt)


class BaseCoreFilter(filters.BaseHostFilter):

    def _get_cpu_allocation_ratio(self, host_state, filter_properties):
        raise NotImplementedError

    def host_passes(self, host_state, filter_properties):
        """Return True if host has sufficient CPU cores."""
        instance_type = filter_properties.get('instance_type')
        if not instance_type:
            return True

        if not host_state.vcpus_total:
            # Fail safe
            LOG.warning(_LW("VCPUs not set; assuming CPU collection broken"))
            return True

        instance_vcpus = instance_type['vcpus']
        cpu_allocation_ratio = self._get_cpu_allocation_ratio(host_state,
                                                          filter_properties)
        vcpus_total = host_state.vcpus_total * cpu_allocation_ratio

        # Only provide a VCPU limit to compute if the virt driver is reporting
        # an accurate count of installed VCPUs. (XenServer driver does not)
        if vcpus_total > 0:
            host_state.limits['vcpu'] = vcpus_total

        free_vcpus = vcpus_total - host_state.vcpus_used
        if free_vcpus < instance_vcpus:
            LOG.debug("%(host_state)s does not have %(instance_vcpus)d "
                      "usable vcpus, it only has %(free_vcpus)d usable "
                      "vcpus",
                      {'host_state': host_state,
                       'instance_vcpus': instance_vcpus,
                       'free_vcpus': free_vcpus})
            return False

        return True


class CoreFilter(BaseCoreFilter):
    """CoreFilter filters based on CPU core utilization."""

    def _get_cpu_allocation_ratio(self, host_state, filter_properties):
        return CONF.cpu_allocation_ratio


class AggregateCoreFilter(BaseCoreFilter):
    """AggregateCoreFilter with per-aggregate CPU subscription flag.

    Fall back to global cpu_allocation_ratio if no per-aggregate setting found.
    """

    def _get_cpu_allocation_ratio(self, host_state, filter_properties):
        # TODO(uni): DB query in filter is a performance hit, especially for
        # system with lots of hosts. Will need a general solution here to fix
        # all filters with aggregate DB call things.
        aggregate_vals = utils.aggregate_values_from_db(
            filter_properties['context'],
            host_state.host,
            'cpu_allocation_ratio')
        try:
            ratio = utils.validate_num_values(
                aggregate_vals, CONF.cpu_allocation_ratio, cast_to=float)
        except ValueError as e:
            LOG.warning(_LW("Could not decode cpu_allocation_ratio: '%s'"), e)
            ratio = CONF.cpu_allocation_ratio

        return ratio
