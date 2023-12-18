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
Hypervisor Version Weigher. Weigh hosts by their relative hypervisor version.

The default is to select newer hosts.  If you prefer
to invert the behavior set the 'hypervisor_version_weight_multiplier' option
to a negative number and the weighing has the opposite effect of the default.
"""

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF


class HypervisorVersionWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'hypervisor_version_weight_multiplier',
            CONF.filter_scheduler.hypervisor_version_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want newer hosts by default."""
        # convert None to 0
        return host_state.hypervisor_version or 0
