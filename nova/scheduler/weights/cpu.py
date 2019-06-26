# Copyright (c) 2016, Red Hat Inc.
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
CPU Weigher.  Weigh hosts by their CPU usage.

The default is to spread instances across all hosts evenly.  If you prefer
stacking, you can set the 'cpu_weight_multiplier' option (by configuration
or aggregate metadata) to a negative number and the weighing has the opposite
effect of the default.
"""

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF


class CPUWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        vcpus_free = (
            host_state.vcpus_total * host_state.cpu_allocation_ratio -
            host_state.vcpus_used)
        return vcpus_free
