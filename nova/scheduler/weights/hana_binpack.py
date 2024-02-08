# Copyright (c) 2024 SAP SE
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
HANA/BigVM Bin-Packing Weigher.

This only runs for flavors having trait:CUSTOM_HANA_EXCLUSIVE_HOST required.
It stacks these VMs by the memory_mb_max_unit reported by the host, where
hosts with a smaller value get a bigger weight.
"""
from oslo_log import log as logging

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights
from nova.utils import BIGVM_EXCLUSIVE_TRAIT

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class HANABinPackWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return -1 * utils.get_weight_multiplier(
            host_state, 'hana_binpack_weight_multiplier',
            CONF.filter_scheduler.hana_binpack_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """We want stacking to be the default."""
        memory_mb_max_unit = utils.get_memory_mb_max_unit(host_state)
        if memory_mb_max_unit is None:
            return 0

        trait = f"trait:{BIGVM_EXCLUSIVE_TRAIT}"
        extra_specs = weight_properties.flavor.extra_specs
        if extra_specs.get(trait) == "required":
            return memory_mb_max_unit

        return 0
