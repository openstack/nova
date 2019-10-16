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

import time

from oslo_log import log as logging

import nova.conf
from nova import context
from nova.scheduler.client import report
from nova.scheduler import filters
from nova.utils import is_big_vm

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class BigVmBaseFilter(filters.BaseHostFilter):

    _HV_SIZE_CACHE = {}
    _HV_SIZE_CACHE_RETENTION_TIME = 10 * 60

    RUN_ON_REBUILD = False

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

    This is used to align with NUMA-properties of a host. We will have flavors
    for half a host and a full host. We allow some tolerance below the exact
    values to account for reserved values.
    """
    _EXTRA_SPECS_KEY = 'host_fraction'
    _HV_SIZE_TOLERANCE_PERCENT = 10

    def _get_supported_fractions(self, hypervisor_ram_mb):
        supported_fractions = {}
        config_fractions = CONF.filter_scheduler.\
                                        bigvm_host_size_filter_host_fractions
        for name, ratio in config_fractions.items():
            ratio = float(ratio)
            if ratio > 1:
                LOG.error('Amount of memory cannot exceed hypervisor memory. '
                          'Wrong configuration in filter_scheduler.'
                          'bigvm_host_size_filter_host_fractions: '
                          '%(config_dict)s.',
                          {'config_dict': config_fractions})
                raise TypeError('bigvm_host_size_filter_host_fractions '
                                'contains invalid values.')
            supported_fractions[name] = hypervisor_ram_mb * ratio

        return supported_fractions

    def _memory_match_with_tolerance(self, memory_mb, requested_ram_mb):
        tolerance = memory_mb * self._HV_SIZE_TOLERANCE_PERCENT / 100.0
        return memory_mb - tolerance <= requested_ram_mb <= memory_mb

    def _check_flavor_extra_specs(self, host_state, flavor,
                                  supported_fractions, requested_ram_mb):
        """Use a flavor attribute to define the fraction of the host this VM
        should match.
        """
        # get the flavor property
        extra_specs = flavor.extra_specs
        # if there's no definition in the big VM flavor, we cannot make an
        # informed decision and bail out
        if self._EXTRA_SPECS_KEY not in extra_specs:
            LOG.info('Flavor %(flavor_name)s has no extra_specs.'
                     '%(specs_key)s. Cannot schedule on %(host_state)s.',
                      {'host_state': host_state,
                       'specs_key': self._EXTRA_SPECS_KEY,
                       'flavor_name': flavor.name})
            return False

        host_fractions = set(
            x.strip() for x in extra_specs[self._EXTRA_SPECS_KEY].split(','))
        known_host_fractions = set(supported_fractions) & host_fractions
        if not known_host_fractions:
            LOG.warning('Flavor attribute %(specs_key)s does not have a '
                        'supported value (%(specs_values)s). Cannot schedule '
                        'on %(host_state)s.',
                        {'host_state': host_state,
                         'specs_key': self._EXTRA_SPECS_KEY,
                         'specs_values': host_fractions})
            return False

        if known_host_fractions != host_fractions:
            LOG.warning('Flavor attribute %(specs_key)s has unsupported '
                        'fractions defined in its values %(specs_values)s.',
                        {'specs_key': self._EXTRA_SPECS_KEY,
                         'specs_values': host_fractions})

        for host_fraction in known_host_fractions:
            memory_mb = supported_fractions[host_fraction]
            if self._memory_match_with_tolerance(memory_mb, requested_ram_mb):
                return True

        LOG.info('%(host_state)s does not match %(requested_ram_mb)s for any '
                 'of the requested fractions %(known_host_fractions)s.',
                 {'host_state': host_state,
                  'requested_ram_mb': requested_ram_mb,
                  'known_host_fractions': known_host_fractions})
        return False

    def _check_no_flavor_extra_specs(self, host_state, supported_fractions,
                                     requested_ram_mb):
        """Check if the VM matches any of the configured fractions."""
        for fraction_ram_mb in supported_fractions.values():
            if self._memory_match_with_tolerance(fraction_ram_mb,
                                                 requested_ram_mb):
                return True

        LOG.info('%(host_state)s does not match %(requested_ram_mb)s for any '
                 'of configured fraction %(supported_fractions)s.',
                 {'host_state': host_state,
                  'requested_ram_mb': requested_ram_mb,
                  'supported_fractions': supported_fractions})
        return False

    def host_passes(self, host_state, spec_obj):
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

        supported_fractions = self._get_supported_fractions(hypervisor_ram_mb)

        flavor_specs_enabled = CONF.filter_scheduler.\
                               bigvm_host_size_filter_uses_flavor_extra_specs
        if flavor_specs_enabled:
            return self._check_flavor_extra_specs(host_state,
                                                  spec_obj.flavor,
                                                  supported_fractions,
                                                  requested_ram_mb)
        else:
            return self._check_no_flavor_extra_specs(host_state,
                                                     supported_fractions,
                                                     requested_ram_mb)
