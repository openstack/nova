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

from oslo_config import cfg
from oslo_log import log as logging
import six

from nova import exception
from nova.objects import fields
from nova.objects import pci_device_pool
from nova.pci import utils
from nova.pci import whitelist


CONF = cfg.CONF
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
    information and selects the compute node accordingly. If a compute
    node is selected, the resource tracker allocates the devices to the
    instance and updates the pci stats information.

    This summary information will be helpful for cloud management also.
    """

    pool_keys = ['product_id', 'vendor_id', 'numa_node', 'dev_type']

    def __init__(self, stats=None, dev_filter=None):
        super(PciDeviceStats, self).__init__()
        # NOTE(sbauza): Stats are a PCIDevicePoolList object
        self.pools = [pci_pool.to_dict()
                      for pci_pool in stats] if stats else []
        self.pools.sort(key=lambda item: len(item))
        self.dev_filter = dev_filter or whitelist.Whitelist(
            CONF.pci.passthrough_whitelist)

    def _equal_properties(self, dev, entry, matching_keys):
        return all(dev.get(prop) == entry.get(prop)
                   for prop in matching_keys)

    def _find_pool(self, dev_pool):
        """Return the first pool that matches dev."""
        for pool in self.pools:
            pool_keys = pool.copy()
            del pool_keys['count']
            del pool_keys['devices']
            if (len(pool_keys.keys()) == len(dev_pool.keys()) and
                self._equal_properties(dev_pool, pool_keys, dev_pool.keys())):
                return pool

    def _create_pool_keys_from_dev(self, dev):
        """create a stats pool dict that this dev is supposed to be part of

        Note that this pool dict contains the stats pool's keys and their
        values. 'count' and 'devices' are not included.
        """
        # Don't add a device that doesn't have a matching device spec.
        # This can happen during initial sync up with the controller
        devspec = self.dev_filter.get_devspec(dev)
        if not devspec:
            return
        tags = devspec.get_tags()
        pool = {k: getattr(dev, k) for k in self.pool_keys}
        if tags:
            pool.update(tags)
        return pool

    def add_device(self, dev):
        """Add a device to its matching pool."""
        dev_pool = self._create_pool_keys_from_dev(dev)
        if dev_pool:
            pool = self._find_pool(dev_pool)
            if not pool:
                dev_pool['count'] = 0
                dev_pool['devices'] = []
                self.pools.append(dev_pool)
                self.pools.sort(key=lambda item: len(item))
                pool = dev_pool
            pool['count'] += 1
            pool['devices'].append(dev)

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

    def remove_device(self, dev):
        """Remove one device from the first pool that it matches."""
        dev_pool = self._create_pool_keys_from_dev(dev)
        if dev_pool:
            pool = self._find_pool(dev_pool)
            if not pool:
                raise exception.PciDevicePoolEmpty(
                    compute_node_id=dev.compute_node_id, address=dev.address)
            pool['devices'].remove(dev)
            self._decrease_pool_count(self.pools, pool)

    def get_free_devs(self):
        free_devs = []
        for pool in self.pools:
            free_devs.extend(pool['devices'])
        return free_devs

    def consume_requests(self, pci_requests, numa_cells=None):
        alloc_devices = []
        for request in pci_requests:
            count = request.count
            spec = request.spec
            # For now, keep the same algorithm as during scheduling:
            # a spec may be able to match multiple pools.
            pools = self._filter_pools_for_spec(self.pools, spec)
            if numa_cells:
                numa_policy = None
                if 'numa_policy' in request:
                    numa_policy = request.numa_policy
                pools = self._filter_pools_for_numa_cells(
                    pools, numa_cells, numa_policy, count)
            pools = self._filter_non_requested_pfs(pools, request)
            # Failed to allocate the required number of devices
            # Return the devices already allocated back to their pools
            if sum([pool['count'] for pool in pools]) < count:
                LOG.error("Failed to allocate PCI devices for instance. "
                          "Unassigning devices back to pools. "
                          "This should not happen, since the scheduler "
                          "should have accurate information, and allocation "
                          "during claims is controlled via a hold "
                          "on the compute node semaphore.")
                for d in range(len(alloc_devices)):
                    self.add_device(alloc_devices.pop())
                return None
            for pool in pools:
                if pool['count'] >= count:
                    num_alloc = count
                else:
                    num_alloc = pool['count']
                count -= num_alloc
                pool['count'] -= num_alloc
                for d in range(num_alloc):
                    pci_dev = pool['devices'].pop()
                    self._handle_device_dependents(pci_dev)
                    pci_dev.request_id = request.request_id
                    alloc_devices.append(pci_dev)
                if count == 0:
                    break
        return alloc_devices

    def _handle_device_dependents(self, pci_dev):
        """Remove device dependents or a parent from pools.

        In case the device is a PF, all of it's dependent VFs should
        be removed from pools count, if these are present.
        When the device is a VF, it's parent PF pool count should be
        decreased, unless it is no longer in a pool.
        """
        if pci_dev.dev_type == fields.PciDeviceType.SRIOV_PF:
            vfs_list = pci_dev.child_devices
            if vfs_list:
                for vf in vfs_list:
                    self.remove_device(vf)
        elif pci_dev.dev_type == fields.PciDeviceType.SRIOV_VF:
            try:
                parent = pci_dev.parent_device
                # Make sure not to decrease PF pool count if this parent has
                # been already removed from pools
                if parent in self.get_free_devs():
                    self.remove_device(parent)
            except exception.PciDeviceNotFound:
                return

    @staticmethod
    def _filter_pools_for_spec(pools, request_specs):
        return [pool for pool in pools
                if utils.pci_device_prop_match(pool, request_specs)]

    @classmethod
    def _filter_pools_for_numa_cells(cls, pools, numa_cells, numa_policy,
            requested_count):
        """Filter out pools with the wrong NUMA affinity, if required.

        Exclude pools that do not have *suitable* PCI NUMA affinity.
        ``numa_policy`` determines what *suitable* means, being one of
        PREFERRED (nice-to-have), LEGACY (must-have-if-available) and REQUIRED
        (must-have). We iterate through the various policies in order of
        strictness. This means that even if we only *prefer* PCI-NUMA affinity,
        we will still attempt to provide it if possible.

        :param pools: A list of PCI device pool dicts
        :param numa_cells: A list of InstanceNUMACell objects whose ``id``
            corresponds to the ``id`` of host NUMACells.
        :param numa_policy: The PCI NUMA affinity policy to apply.
        :param requested_count: The number of PCI devices requested.
        :returns: A list of pools that can, together, provide at least
            ``requested_count`` PCI devices with the level of NUMA affinity
            required by ``numa_policy``, else all pools that can satisfy this
            policy even if it's not enough.
        """
        # NOTE(stephenfin): We may wish to change the default policy at a later
        # date
        requested_policy = numa_policy or fields.PCINUMAAffinityPolicy.LEGACY
        numa_cell_ids = [cell.id for cell in numa_cells]

        # filter out pools which numa_node is not included in numa_cell_ids
        filtered_pools = [
            pool for pool in pools if any(utils.pci_device_prop_match(
                pool, [{'numa_node': cell}]) for cell in numa_cell_ids)]

        # we can't apply a less strict policy than the one requested, so we
        # need to return if we've demanded a NUMA affinity of REQUIRED.
        # However, NUMA affinity is a good thing. If we can get enough devices
        # with the stricter policy then we will use them.
        if requested_policy == fields.PCINUMAAffinityPolicy.REQUIRED or sum(
                pool['count'] for pool in filtered_pools) >= requested_count:
            return filtered_pools

        # some systems don't report NUMA node info for PCI devices, in which
        # case None is reported in 'pci_device.numa_node'. The LEGACY policy
        # allows us to use these devices so we include None in the list of
        # suitable NUMA cells.
        numa_cell_ids.append(None)

        # filter out pools which numa_node is not included in numa_cell_ids
        filtered_pools = [
            pool for pool in pools if any(utils.pci_device_prop_match(
                pool, [{'numa_node': cell}]) for cell in numa_cell_ids)]

        # once again, we can't apply a less strict policy than the one
        # requested, so we need to return if we've demanded a NUMA affinity of
        # LEGACY. Similarly, we will also return if we have enough devices to
        # satisfy this somewhat strict policy.
        if requested_policy == fields.PCINUMAAffinityPolicy.LEGACY or sum(
                pool['count'] for pool in filtered_pools) >= requested_count:
            return filtered_pools

        # if we've got here, we're using the PREFERRED policy and weren't able
        # to provide anything with stricter affinity. Use whatever devices you
        # can, folks.
        return sorted(
            pools, key=lambda pool: pool.get('numa_node') not in numa_cell_ids)

    @classmethod
    def _filter_non_requested_pfs(cls, pools, request):
        # Remove SRIOV_PFs from pools, unless it has been explicitly requested
        # This is especially needed in cases where PFs and VFs have the same
        # product_id.
        if all(spec.get('dev_type') != fields.PciDeviceType.SRIOV_PF for
               spec in request.spec):
            pools = cls._filter_pools_for_pfs(pools)
        return pools

    @staticmethod
    def _filter_pools_for_pfs(pools):
        return [pool for pool in pools
                if not pool.get('dev_type') == fields.PciDeviceType.SRIOV_PF]

    def _apply_request(self, pools, request, numa_cells=None):
        """Apply a PCI request.

        Apply a PCI request against a given set of PCI device pools, which are
        collections of devices with similar traits.

        If ``numa_cells`` is provided then NUMA locality may be taken into
        account, depending on the value of ``request.numa_policy``.

        :param pools: A list of PCI device pool dicts
        :param request: An InstancePCIRequest object describing the type,
            quantity and required NUMA affinity of device(s) we want..
        :param numa_cells: A list of InstanceNUMACell objects whose ``id``
            corresponds to the ``id`` of host NUMACells.
        :returns: True if the request was applied against the provided pools
            successfully, else False.
        """
        # NOTE(vladikr): This code maybe open to race conditions.
        # Two concurrent requests may succeed when called support_requests
        # because this method does not remove related devices from the pools
        count = request.count

        # Firstly, let's exclude all devices that don't match our spec (e.g.
        # they've got different PCI IDs or something)
        matching_pools = self._filter_pools_for_spec(pools, request.spec)

        # Next, let's exclude all devices that aren't on the correct NUMA node
        # *assuming* we have devices and care about that, as determined by
        # policy
        if numa_cells:
            numa_policy = None
            if 'numa_policy' in request:
                numa_policy = request.numa_policy

            matching_pools = self._filter_pools_for_numa_cells(matching_pools,
                numa_cells, numa_policy, count)

        # Finally, if we're not requesting PFs then we should not use these.
        # Exclude them.
        matching_pools = self._filter_non_requested_pfs(matching_pools,
                                                        request)

        # Do we still have any devices left?
        if sum([pool['count'] for pool in matching_pools]) < count:
            return False
        else:
            for pool in matching_pools:
                count = self._decrease_pool_count(pools, pool, count)
                if not count:
                    break
        return True

    def support_requests(self, requests, numa_cells=None):
        """Determine if the PCI requests can be met.

        Determine, based on a compute node's PCI stats, if an instance can be
        scheduled on the node. **Support does not mean real allocation**.

        If ``numa_cells`` is provided then NUMA locality may be taken into
        account, depending on the value of ``numa_policy``.

        :param requests: A list of InstancePCIRequest object describing the
            types, quantities and required NUMA affinities of devices we want.
        :type requests: nova.objects.InstancePCIRequests
        :param numa_cells: A list of InstanceNUMACell objects whose ``id``
            corresponds to the ``id`` of host NUMACells, or None.
        :returns: Whether this compute node can satisfy the given request.
        """
        # note (yjiang5): this function has high possibility to fail,
        # so no exception should be triggered for performance reason.
        pools = copy.deepcopy(self.pools)
        return all(self._apply_request(pools, r, numa_cells) for r in requests)

    def apply_requests(self, requests, numa_cells=None):
        """Apply PCI requests to the PCI stats.

        This is used in multiple instance creation, when the scheduler has to
        maintain how the resources are consumed by the instances.

        If ``numa_cells`` is provided then NUMA locality may be taken into
        account, depending on the value of ``numa_policy``.

        :param requests: A list of InstancePCIRequest object describing the
            types, quantities and required NUMA affinities of devices we want.
        :type requests: nova.objects.InstancePCIRequests
        :param numa_cells: A list of InstanceNUMACell objects whose ``id``
            corresponds to the ``id`` of host NUMACells, or None.
        :raises: exception.PciDeviceRequestFailed if this compute node cannot
            satisfy the given request.
        """
        if not all(self._apply_request(self.pools, r, numa_cells)
                   for r in requests):
            raise exception.PciDeviceRequestFailed(requests=requests)

    def __iter__(self):
        # 'devices' shouldn't be part of stats
        pools = []
        for pool in self.pools:
            tmp = {k: v for k, v in pool.items() if k != 'devices'}
            pools.append(tmp)
        return iter(pools)

    def clear(self):
        """Clear all the stats maintained."""
        self.pools = []

    def __eq__(self, other):
        return self.pools == other.pools

    if six.PY2:
        def __ne__(self, other):
            return not (self == other)

    def to_device_pools_obj(self):
        """Return the contents of the pools as a PciDevicePoolList object."""
        stats = [x for x in self]
        return pci_device_pool.from_pci_stats(stats)
