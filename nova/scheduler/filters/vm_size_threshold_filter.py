# Copyright (c) 2021 SAP SE
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
from nova import utils as nova_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class VmSizeThresholdFilter(filters.BaseHostFilter, HypervisorSizeMixin):
    """Make sure we schedule too big VMs not onto too small hypervisors.

    Any VM bigger or equal to
    CONF.filter_scheduler.vm_size_threshold_vm_size_mb will not be able to
    spawn on a hypervisor smaller than
    CONF.filter_scheduler.vm_size_threshold_hv_size_mb.
    """
    @property
    def _vm_size_threshold_mb(self):
        return CONF.filter_scheduler.vm_size_threshold_vm_size_mb

    @property
    def _hv_size_threshold_mb(self):
        return CONF.filter_scheduler.vm_size_threshold_hv_size_mb

    def host_passes(self, host_state, spec_obj):
        # While theoretically, the logic makes also sense
        # for other hypervisors, we do not have the hardware
        # to place the requests that granular yet.
        # Depending on how the hardware looks like,
        # we might want to revisit the logic.
        # I.e. either remove this check, or differentiate it
        # according to the hypervisor
        if utils.is_non_vmware_spec(spec_obj):
            return True

        # ignore baremetal.
        if nova_utils.is_baremetal_flavor(spec_obj.flavor):
            return True

        requested_ram_mb = spec_obj.memory_mb
        # VM is too small for this filter
        if requested_ram_mb < self._vm_size_threshold_mb:
            return True

        hypervisor_ram_mb = self._get_hv_size(host_state)
        if hypervisor_ram_mb is None:
            LOG.debug('Cannot retrieve hypervisor size for %(host_state)s.',
                      {'host_state': host_state})
            return False

        # HV is too small for this VM
        if hypervisor_ram_mb < self._hv_size_threshold_mb:
            LOG.info('%(host_state)s is too small (< %(hv_threshold)s MB) to '
                     'be allowed to spawn a VM of size %(requested_ram_mb)s '
                     'MB (>= %(vm_threshold)s)',
                     {'host_state': host_state,
                      'requested_ram_mb': requested_ram_mb,
                      'hv_threshold': self._hv_size_threshold_mb,
                      'vm_threshold': self._vm_size_threshold_mb})
            return False

        return True
