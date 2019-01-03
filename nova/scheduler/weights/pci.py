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
PCI Affinity Weigher.  Weigh hosts by their PCI availability.

Prefer hosts with PCI devices for instances with PCI requirements and vice
versa. Configure the importance of this affinitization using the
'pci_weight_multiplier' option (by configuration or aggregate metadata).
"""

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF

# An arbitrary value used to ensure PCI-requesting instances are stacked rather
# than spread on hosts with PCI devices. The actual value of this filter is in
# the scarcity case, where there are very few PCI devices left in the cloud and
# we want to preserve the ones that do exist. To this end, we don't really mind
# if a host with 2000 PCI devices is weighted the same as one with 500 devices,
# as there's clearly no shortage there.
MAX_DEVS = 100


class PCIWeigher(weights.BaseHostWeigher):

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'pci_weight_multiplier',
            CONF.filter_scheduler.pci_weight_multiplier)

    def _weigh_object(self, host_state, request_spec):
        """Higher weights win. We want to keep PCI hosts free unless needed.

        Prefer hosts with the least number of PCI devices. If the instance
        requests PCI devices, this will ensure a stacking behavior and reserve
        as many totally free PCI hosts as possible. If PCI devices are not
        requested, this will ensure hosts with PCI devices are avoided
        completely, if possible.
        """
        pools = host_state.pci_stats.pools if host_state.pci_stats else []
        free = sum(pool['count'] for pool in pools) or 0

        # reverse the "has PCI" values. For instances *without* PCI device
        # requests, this ensures we avoid the hosts with the most free PCI
        # devices. For the instances *with* PCI devices requests, this helps to
        # prevent fragmentation. If we didn't do this, hosts with the most PCI
        # devices would be weighted highest and would be used first which would
        # prevent instances requesting a larger number of PCI devices from
        # launching successfully.
        weight = MAX_DEVS - min(free, MAX_DEVS - 1)

        return weight
