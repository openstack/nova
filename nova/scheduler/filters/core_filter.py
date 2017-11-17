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

from oslo_log import log as logging

from nova.i18n import _LW
from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)


class BaseCoreFilter(filters.BaseHostFilter):

    RUN_ON_REBUILD = False

    def _get_cpu_allocation_ratio(self, host_state, spec_obj):
        raise NotImplementedError

    def host_passes(self, host_state, spec_obj):
        """Return True if host has sufficient CPU cores.

        :param host_state: nova.scheduler.host_manager.HostState
        :param spec_obj: filter options
        :return: boolean
        """
        if not host_state.vcpus_total:
            # Fail safe
            LOG.warning(_LW("VCPUs not set; assuming CPU collection broken"))
            return True

        instance_vcpus = spec_obj.vcpus
        cpu_allocation_ratio = self._get_cpu_allocation_ratio(host_state,
                                                              spec_obj)
        vcpus_total = host_state.vcpus_total * cpu_allocation_ratio

        # Only provide a VCPU limit to compute if the virt driver is reporting
        # an accurate count of installed VCPUs. (XenServer driver does not)
        if vcpus_total > 0:
            host_state.limits['vcpu'] = vcpus_total

            # Do not allow an instance to overcommit against itself, only
            # against other instances.
            if instance_vcpus > host_state.vcpus_total:
                LOG.debug("%(host_state)s does not have %(instance_vcpus)d "
                          "total cpus before overcommit, it only has %(cpus)d",
                          {'host_state': host_state,
                           'instance_vcpus': instance_vcpus,
                           'cpus': host_state.vcpus_total})
                return False

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

    def _get_cpu_allocation_ratio(self, host_state, spec_obj):
        return host_state.cpu_allocation_ratio


class AggregateCoreFilter(BaseCoreFilter):
    """AggregateCoreFilter with per-aggregate CPU subscription flag.

    Fall back to global cpu_allocation_ratio if no per-aggregate setting found.
    """

    def _get_cpu_allocation_ratio(self, host_state, spec_obj):
        aggregate_vals = utils.aggregate_values_from_key(
            host_state,
            'cpu_allocation_ratio')
        try:
            ratio = utils.validate_num_values(
                aggregate_vals, host_state.cpu_allocation_ratio, cast_to=float)
        except ValueError as e:
            LOG.warning(_LW("Could not decode cpu_allocation_ratio: '%s'"), e)
            ratio = host_state.cpu_allocation_ratio

        return ratio
