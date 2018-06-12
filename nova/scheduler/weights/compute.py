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
BuildFailure Weigher. Weigh hosts by the number of recent failed boot attempts.

"""

import nova.conf
from nova.scheduler import weights

CONF = nova.conf.CONF


class BuildFailureWeigher(weights.BaseHostWeigher):
    def weight_multiplier(self):
        """Override the weight multiplier. Note this is negated."""
        return -1 * CONF.filter_scheduler.build_failure_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  Our multiplier is negative, so reduce our
           weight by number of failed builds.
        """
        return host_state.failed_builds
