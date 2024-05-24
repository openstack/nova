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
Weigh down HVs with the sapphire rapids trait, so that old hardware is
preferred. Since flavors requesting sapphire rapids BBs do not have any
non-sapphire rapids BBs, this does not change the normalized weight.
"""
from oslo_log import log as logging

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

SR_TRAIT = 'CUSTOM_HW_SAPPHIRE_RAPIDS'


class SapphireRapidsWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return -1 * utils.get_weight_multiplier(
            host_state, 'sapphire_rapids_weight_multiplier',
            CONF.filter_scheduler.sapphire_rapids_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """De-prioritise sapphire rapids hosts."""
        if host_state.traits and SR_TRAIT in host_state.traits:
            return 1.0
        return 0.0
