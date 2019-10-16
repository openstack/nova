# Copyright (c) 2019 OpenStack Foundation
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
from nova.scheduler.mixins import HypervisorSizeMixin
from nova.scheduler import utils
from nova.utils import is_big_vm

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class BigVmBaseFilter(filters.BaseHostFilter, HypervisorSizeMixin):

    RUN_ON_REBUILD = False


class BigVmClusterUtilizationFilter(BigVmBaseFilter):
    """Only schedule big VMs to a vSphere cluster (i.e. nova-compute host) if
    the memory-utilization of the cluster is below a threshold depending on the
    hypervisor size and the requested memory.
    """

    def _get_max_ram_percent(self, requested_ram_mb, hypervisor_ram_mb):
        """We want the hosts to have on average half the requested memory free.
        """
        requested_ram_mb = float(requested_ram_mb)
        hypervisor_ram_mb = float(hypervisor_ram_mb)
        hypervisor_max_used_ram_mb = hypervisor_ram_mb - requested_ram_mb / 2
        return hypervisor_max_used_ram_mb / hypervisor_ram_mb * 100

    def host_passes(self, host_state, spec_obj):
        if utils.is_non_vmware_spec(spec_obj):
            return True

        requested_ram_mb = spec_obj.memory_mb
        # not scheduling a big VM -> every host is fine
        if not is_big_vm(requested_ram_mb, spec_obj.flavor):
            return True

        hypervisor_ram_mb = self._get_hv_size(host_state)
        if hypervisor_ram_mb is None:
            return False

        free_ram_mb = host_state.free_ram_mb
        total_usable_ram_mb = host_state.total_usable_ram_mb
        used_ram_mb = total_usable_ram_mb - free_ram_mb
        used_ram_percent = float(used_ram_mb) / total_usable_ram_mb * 100.0

        max_ram_percent = self._get_max_ram_percent(requested_ram_mb,
                                                    hypervisor_ram_mb)

        if used_ram_percent > max_ram_percent:
            LOG.info("%(host_state)s does not have less than "
                      "%(max_ram_percent)s %% RAM utilization (has "
                      "%(used_ram_percent)s %%) and is thus not suitable "
                      "for big VMs.",
                      {'host_state': host_state,
                       'max_ram_percent': max_ram_percent,
                       'used_ram_percent': used_ram_percent})
            return False

        return True


class BigVmFlavorHostSizeFilter(BigVmBaseFilter):
    """Filter out hosts not matching the flavor's property for supported
    host-sizes.

    This is used to align with NUMA-properties of a host. The flavor supports a
    "host_fraction" RAM fill ratio. We allow some tolerance below the exact
    values to account for reserved values.
    """
    _EXTRA_SPECS_KEY = 'host_fraction'
    _HV_SIZE_TOLERANCE_PERCENT = 10
    _NUMA_TRAIT_SPEC_PREFIX = 'trait:CUSTOM_NUMASIZE_'

    def _memory_match_with_tolerance(self, memory_mb, requested_ram_mb):
        """Return True if requested_ram_mb is equal to memory_mb or down to
        _HV_SIZE_TOLERANCE_PERCENT *below* that.
        """
        tolerance = memory_mb * self._HV_SIZE_TOLERANCE_PERCENT / 100.0
        return memory_mb - tolerance <= requested_ram_mb <= memory_mb

    def _get_numa_trait_requirement(self, extra_specs):
        """Return the (first) extra_specs key for required numa host traits."""
        try:
            return next(k for k, v in extra_specs.items()
                        if k.startswith(self._NUMA_TRAIT_SPEC_PREFIX) and
                            v == "required")
        except StopIteration:
            return None

    def _check_flavor_extra_specs(self, host_state, flavor,
                                  hypervisor_ram_mb, requested_ram_mb):
        """Use a flavor attribute to define the fraction of the host this VM
        should match.
        """
        extra_specs = flavor.extra_specs

        # Check if we ask for a specific NUMA trait and if so we assume this
        # cluster already matched via trait requirement in placement.
        numa_trait_spec = self._get_numa_trait_requirement(extra_specs)
        if numa_trait_spec:
            LOG.debug('Flavor %(flavor_name)s has NUMA host requirement '
                      '%(numa_trait) set. Host-fraction filtering ignored.',
                      {'flavor_name': flavor.name,
                       'numa_trait': numa_trait_spec.replace('trait:', '')})
            return True

        # if numa trait is not set and there's no host_fraction definition in
        # the big VM flavor, we cannot make an informed decision and bail out
        if self._EXTRA_SPECS_KEY not in extra_specs:
            LOG.info('Flavor %(flavor_name)s has no extra_specs.'
                     '%(specs_key)s. Cannot schedule on %(host_state)s.',
                      {'host_state': host_state,
                       'specs_key': self._EXTRA_SPECS_KEY,
                       'flavor_name': flavor.name})
            return False

        host_fractions = set()
        for x in extra_specs[self._EXTRA_SPECS_KEY].split(','):
            if '/' in x:
                x, y = x.split('/')
                try:
                    ratio = float(x) / float(y)
                except (ValueError, ZeroDivisionError):
                    continue
            else:
                try:
                    ratio = float(x)
                except ValueError:
                    continue
            if 0.0 <= ratio <= 1.0:
                host_fractions.add(ratio * hypervisor_ram_mb)
        if not host_fractions:
            LOG.warning('Flavor attribute %(specs_key)s does not have any '
                        'supported value (\'%(specs_ratio_values)s\' => '
                        '%(specs_fraction_values)s). Cannot schedule on '
                        '%(host_state)s.',
                        {'host_state': host_state,
                         'specs_key': self._EXTRA_SPECS_KEY,
                         'specs_ratio_values':
                            extra_specs[self._EXTRA_SPECS_KEY],
                         'specs_fraction_values': list(host_fractions)})
            return False

        for host_fraction in host_fractions:
            if self._memory_match_with_tolerance(
                    host_fraction, requested_ram_mb):
                return True

        LOG.info('%(host_state)s does not match %(requested_ram_mb)s for any '
                 'of the requested fractions %(host_fractions)s.',
                 {'host_state': host_state,
                  'requested_ram_mb': requested_ram_mb,
                  'host_fractions': host_fractions})
        return False

    def host_passes(self, host_state, spec_obj):
        if utils.is_non_vmware_spec(spec_obj):
            return True

        requested_ram_mb = spec_obj.memory_mb
        # not scheduling a big VM -> every host is fine
        if not is_big_vm(requested_ram_mb, spec_obj.flavor):
            return True

        hypervisor_ram_mb = self._get_hv_size(host_state)
        # skip this host as we cannot determine if we fit
        if hypervisor_ram_mb is None:
            LOG.debug('Cannot retrieve hypervisor size for %(host_state)s.',
                      {'host_state': host_state})
            return False

        return self._check_flavor_extra_specs(host_state,
                                              spec_obj.flavor,
                                              hypervisor_ram_mb,
                                              requested_ram_mb)
