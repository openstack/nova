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
Num instances Weigher. Weigh hosts by their number of instances.

The default is to select hosts with less instances for a spreading strategy.
If you prefer to invert this behavior set the 'num_instances_weight_multiplier'
option to a positive number and the weighing has the opposite effect of the
default.
"""

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF


class NumInstancesWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'num_instances_weight_multiplier',
            CONF.filter_scheduler.num_instances_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want to choose hosts with fewer instances
           as the default, hence the negative value of the multiplier.
        """
        return host_state.num_instances
