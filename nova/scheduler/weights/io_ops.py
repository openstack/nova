# Copyright (c) 2014 OpenStack Foundation
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
Io Ops Weigher. Weigh hosts by their io ops number.

The default is to preferably choose light workload compute hosts. If you prefer
choosing heavy workload compute hosts, you can set 'io_ops_weight_multiplier'
option to a positive number and the weighing has the opposite effect of the
default.
"""

import nova.conf
from nova.scheduler import weights

CONF = nova.conf.CONF


class IoOpsWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.filter_scheduler.io_ops_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win. We want to choose light workload host
        to be the default.
        """
        return host_state.num_io_ops
