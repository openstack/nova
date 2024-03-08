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
Decommissioning Weigher.

De-prioritise the hosts which are being decommissioned, by always placing
them the last in the queue.
Allow such hosts to be scheduled only when absolutely necessary, i.e.
when all other hosts are full.
"""

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF

DECOM_TRAIT = 'CUSTOM_DECOMMISSIONING'


class DecommissioningWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return -1 * utils.get_weight_multiplier(
            host_state, 'decommissioning_weight_multiplier',
            CONF.filter_scheduler.decommissioning_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """De-prioritise decommissioning hosts."""
        if host_state.traits and DECOM_TRAIT in host_state.traits:
            return 1.0
        return 0.0
