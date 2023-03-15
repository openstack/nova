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
"""
VmHvRatioWeigher. Weigh hosts by how well they fit the VM size.
"""
from operator import itemgetter

from oslo_log import log as logging

import nova.conf
from nova.scheduler.mixins import HypervisorSizeMixin
from nova.scheduler import utils
from nova.scheduler import weights

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class HvRamClassWeigher(weights.BaseHostWeigher, HypervisorSizeMixin):
    minval = 0

    def __init__(self, *args, **kwargs):
        weights.BaseHostWeigher.__init__(self, *args, **kwargs)
        self._load_classes()

    def _load_classes(self):
        """Split out from __init__() to be able to unit-test better"""
        config_weights = CONF.filter_scheduler.hv_ram_class_weights_gib
        classes = [(int(ram) * 1024, float(weight))
                   for ram, weight in config_weights.items()]

        self._classes = sorted(classes, key=itemgetter(0), reverse=True)
        self.maxval = classes[0][1]

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'hv_ram_class_weight_multiplier',
            CONF.filter_scheduler.hv_ram_class_weight_multiplier)

        return CONF.filter_scheduler.hv_ram_class_weight_multiplier

    def _weigh_object(self, host_state, request_spec):
        """Assign the HV a pre-defined weight based on its RAM

        We want to fill up HVs by best fit, but don't want small differences in
        the amount of RAM an HV has to offer to matter. Therefore, we use
        configurable classes with weights, defined by an upper bound of RAM.
        """
        # ignore non-vmware scheduling requests
        if utils.is_non_vmware_spec(request_spec):
            return self.minval

        hypervisor_ram_mb = self._get_hv_size(host_state)
        if not hypervisor_ram_mb:
            LOG.debug('Cannot retrieve hypervisor size for %(host_state)s.',
                      {'host_state': host_state})
            return self.minval

        weight = self.minval

        for ram_class_mb, next_weight in self._classes:
            if hypervisor_ram_mb > ram_class_mb:
                return weight
            weight = next_weight

        return weight
