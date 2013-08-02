# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

import copy

from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.pci import pci_utils


LOG = logging.getLogger(__name__)


class PciDeviceStats(object):

    """PCI devices summary information.

    According to the PCI SR-IOV spec, a PCI physical function can have up to
    256 PCI virtual functions, thus the number of assignable PCI functions in
    a cloud can be big. The scheduler needs to know all device availability
    information in order to determine which compute hosts can support a PCI
    request. Passing individual virtual device information to the scheduler
    does not scale, so we provide summary information.

    Usually the virtual functions provided by a host PCI device have the same
    value for most properties, like vendor_id, product_id and class type.
    The PCI stats class summarizes this information for the scheduler.

    The pci stats information is maintained exclusively by compute node
    resource tracker and updated to database. The scheduler fetches the
    information and selects the compute node accordingly. If a comptue
    node is selected, the resource tracker allocates the devices to the
    instance and updates the pci stats information.

    This summary information will be helpful for cloud management also.
    """

    pool_keys = ['product_id', 'vendor_id', 'extra_info']

    def __init__(self, stats=None):
        super(PciDeviceStats, self).__init__()
        self.pools = jsonutils.loads(stats) if stats else []

    def _equal_properties(self, dev, entry):
        return all(dev.get(prop) == entry.get(prop)
                   for prop in self.pool_keys)

    def _get_first_pool(self, dev):
        """Return the first pool that matches dev."""
        return next((pool for pool in self.pools
                    if self._equal_properties(dev, pool)), None)

    def add_device(self, dev):
        """Add a device to the first matching pool."""
        pool = self._get_first_pool(dev)
        if not pool:
            pool = dict((k, dev.get(k)) for k in self.pool_keys)
            pool['count'] = 0
            self.pools.append(pool)
        pool['count'] += 1

    @staticmethod
    def _decrease_pool_count(pool_list, pool, count=1):
        """Decrement pool's size by count.

        If pool becomes empty, remove pool from pool_list.
        """
        if pool['count'] > count:
            pool['count'] -= count
            count = 0
        else:
            count -= pool['count']
            pool_list.remove(pool)
        return count

    def consume_device(self, dev):
        """Remove one device from the first pool that it matches."""
        pool = self._get_first_pool(dev)
        if not pool:
            raise exception.PciDevicePoolEmpty(
                compute_node_id=dev.compute_node_id, address=dev.address)
        self._decrease_pool_count(self.pools, pool)

    @staticmethod
    def _filter_pools_for_spec(pools, request_specs):
        return [pool for pool in pools
                if pci_utils.pci_device_prop_match(pool, request_specs)]

    def _apply_request(self, pools, request):
        count = request['count']
        matching_pools = self._filter_pools_for_spec(pools, request['spec'])
        if sum([pool['count'] for pool in matching_pools]) < count:
            return False
        else:
            for pool in matching_pools:
                count = self._decrease_pool_count(pools, pool, count)
                if not count:
                    break
        return True

    def support_requests(self, requests):
        """Check if the pci requests can be met.

        Scheduler checks compute node's PCI stats to decide if an
        instance can be scheduled into the node. Support does not
        mean real allocation.
        """
        # note (yjiang5): this function has high possibility to fail,
        # so no exception should be triggered for performance reason.
        pools = copy.deepcopy(self.pools)
        return all([self._apply_request(pools, r) for r in requests])

    def apply_requests(self, requests):
        """Apply PCI requests to the PCI stats.

        This is used in multiple instance creation, when the scheduler has to
        maintain how the resources are consumed by the instances.
        """
        if not all([self._apply_request(self.pools, r) for r in requests]):
            raise exception.PciDeviceRequestFailed(requests=requests)

    def __iter__(self):
        return iter(self.pools)

    def clear(self):
        """Clear all the stats maintained."""
        self.pools = []
