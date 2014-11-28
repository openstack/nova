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

import collections

from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.i18n import _LW
from nova import objects
from nova.openstack.common import log as logging
from nova.pci import device
from nova.pci import stats
from nova.virt import hardware

LOG = logging.getLogger(__name__)


class PciDevTracker(object):
    """Manage pci devices in a compute node.

    This class fetches pci passthrough information from hypervisor
    and trackes the usage of these devices.

    It's called by compute node resource tracker to allocate and free
    devices to/from instances, and to update the available pci passthrough
    devices information from hypervisor periodically. The devices
    information is updated to DB when devices information is changed.
    """

    def __init__(self, node_id=None):
        """Create a pci device tracker.

        If a node_id is passed in, it will fetch pci devices information
        from database, otherwise, it will create an empty devices list
        and the resource tracker will update the node_id information later.
        """

        super(PciDevTracker, self).__init__()
        self.stale = {}
        self.node_id = node_id
        self.stats = stats.PciDeviceStats()
        if node_id:
            self.pci_devs = list(
                objects.PciDeviceList.get_by_compute_node(context, node_id))
        else:
            self.pci_devs = []
        self._initial_instance_usage()

    def _initial_instance_usage(self):
        self.allocations = collections.defaultdict(list)
        self.claims = collections.defaultdict(list)
        for dev in self.pci_devs:
            uuid = dev['instance_uuid']
            if dev['status'] == 'claimed':
                self.claims[uuid].append(dev)
            elif dev['status'] == 'allocated':
                self.allocations[uuid].append(dev)
            elif dev['status'] == 'available':
                self.stats.add_device(dev)

    @property
    def all_devs(self):
        return self.pci_devs

    def save(self, context):
        for dev in self.pci_devs:
            if dev.obj_what_changed():
                dev.save(context)

        self.pci_devs = [dev for dev in self.pci_devs
                         if dev['status'] != 'deleted']

    @property
    def pci_stats(self):
        return self.stats

    def set_hvdevs(self, devices):
        """Sync the pci device tracker with hypervisor information.

        To support pci device hot plug, we sync with the hypervisor
        periodically, fetching all devices information from hypervisor,
        update the tracker and sync the DB information.

        Devices should not be hot-plugged when assigned to a guest,
        but possibly the hypervisor has no such guarantee. The best
        we can do is to give a warning if a device is changed
        or removed while assigned.
        """

        exist_addrs = set([dev['address'] for dev in self.pci_devs])
        new_addrs = set([dev['address'] for dev in devices])

        for existed in self.pci_devs:
            if existed['address'] in exist_addrs - new_addrs:
                try:
                    device.remove(existed)
                except exception.PciDeviceInvalidStatus as e:
                    LOG.warning(_LW("Trying to remove device with %(status)s "
                                    "ownership %(instance_uuid)s because of "
                                    "%(pci_exception)s"),
                                {'status': existed.status,
                                 'instance_uuid': existed.instance_uuid,
                                 'pci_exception': e.format_message()})
                    # Note(yjiang5): remove the device by force so that
                    # db entry is cleaned in next sync.
                    existed.status = 'removed'
                else:
                    # Note(yjiang5): no need to update stats if an assigned
                    # device is hot removed.
                    self.stats.remove_device(existed)
            else:
                new_value = next((dev for dev in devices if
                    dev['address'] == existed['address']))
                new_value['compute_node_id'] = self.node_id
                if existed['status'] in ('claimed', 'allocated'):
                    # Pci properties may change while assigned because of
                    # hotplug or config changes. Although normally this should
                    # not happen.

                    # As the devices have been assigned to a instance, we defer
                    # the change till the instance is destroyed. We will
                    # not sync the new properties with database before that.

                    # TODO(yjiang5): Not sure if this is a right policy, but
                    # at least it avoids some confusion and, if needed,
                    # we can add more action like killing the instance
                    # by force in future.
                    self.stale[new_value['address']] = new_value
                else:
                    device.update_device(existed, new_value)

        for dev in [dev for dev in devices if
                    dev['address'] in new_addrs - exist_addrs]:
            dev['compute_node_id'] = self.node_id
            dev_obj = objects.PciDevice.create(dev)
            self.pci_devs.append(dev_obj)
            self.stats.add_device(dev_obj)

    def _claim_instance(self, context, instance, prefix=''):
        pci_requests = objects.InstancePCIRequests.get_by_instance(
            context, instance)
        if not pci_requests.requests:
            return None
        instance_numa_topology = hardware.instance_topology_from_instance(
            instance)
        instance_cells = None
        if instance_numa_topology:
            instance_cells = instance_numa_topology.cells

        devs = self.stats.consume_requests(pci_requests.requests,
                                           instance_cells)
        if not devs:
            raise exception.PciDeviceRequestFailed(pci_requests)
        for dev in devs:
            device.claim(dev, instance)
        if instance_numa_topology and any(
                                        dev.numa_node is None for dev in devs):
            LOG.warning(_LW("Assigning a pci device without numa affinity to"
            "instance %(instance)s which has numa topology"),
                        {'instance': instance['uuid']})
        return devs

    def _allocate_instance(self, instance, devs):
        for dev in devs:
            device.allocate(dev, instance)

    def _free_device(self, dev, instance=None):
        device.free(dev, instance)
        stale = self.stale.pop(dev['address'], None)
        if stale:
            device.update_device(dev, stale)
        self.stats.add_device(dev)

    def _free_instance(self, instance):
        # Note(yjiang5): When a instance is resized, the devices in the
        # destination node are claimed to the instance in prep_resize stage.
        # However, the instance contains only allocated devices
        # information, not the claimed one. So we can't use
        # instance['pci_devices'] to check the devices to be freed.
        for dev in self.pci_devs:
            if (dev['status'] in ('claimed', 'allocated') and
                    dev['instance_uuid'] == instance['uuid']):
                self._free_device(dev)

    def update_pci_for_instance(self, context, instance):
        """Update instance's pci usage information.

        The caller should hold the COMPUTE_RESOURCE_SEMAPHORE lock
        """

        uuid = instance['uuid']
        vm_state = instance['vm_state']
        task_state = instance['task_state']

        if vm_state == vm_states.DELETED:
            if self.allocations.pop(uuid, None):
                self._free_instance(instance)
            elif self.claims.pop(uuid, None):
                self._free_instance(instance)
        elif task_state == task_states.RESIZE_MIGRATED:
            devs = self.allocations.pop(uuid, None)
            if devs:
                self._free_instance(instance)
        elif task_state == task_states.RESIZE_FINISH:
            devs = self.claims.pop(uuid, None)
            if devs:
                self._allocate_instance(instance, devs)
                self.allocations[uuid] = devs
        elif (uuid not in self.allocations and
               uuid not in self.claims):
            devs = self._claim_instance(context, instance)
            if devs:
                self._allocate_instance(instance, devs)
                self.allocations[uuid] = devs

    def update_pci_for_migration(self, context, instance, sign=1):
        """Update instance's pci usage information when it is migrated.

        The caller should hold the COMPUTE_RESOURCE_SEMAPHORE lock.

        :param sign: claim devices for instance when sign is 1, remove
                     the claims when sign is -1
        """
        uuid = instance['uuid']
        if sign == 1 and uuid not in self.claims:
            devs = self._claim_instance(context, instance, 'new_')
            if devs:
                self.claims[uuid] = devs
        if sign == -1 and uuid in self.claims:
            self._free_instance(instance)

    def clean_usage(self, instances, migrations, orphans):
        """Remove all usages for instances not passed in the parameter.

        The caller should hold the COMPUTE_RESOURCE_SEMAPHORE lock
        """
        existed = [inst['uuid'] for inst in instances]
        existed += [mig['instance_uuid'] for mig in migrations]
        existed += [inst['uuid'] for inst in orphans]

        for uuid in self.claims.keys():
            if uuid not in existed:
                devs = self.claims.pop(uuid, [])
                for dev in devs:
                    self._free_device(dev)
        for uuid in self.allocations.keys():
            if uuid not in existed:
                devs = self.allocations.pop(uuid, [])
                for dev in devs:
                    self._free_device(dev)

    def set_compute_node_id(self, node_id):
        """Set the compute node id that this object is tracking for.

        In current resource tracker implementation, the
        compute_node entry is created in the last step of
        update_available_resoruces, thus we have to lazily set the
        compute_node_id at that time.
        """

        if self.node_id and self.node_id != node_id:
            raise exception.PciTrackerInvalidNodeId(node_id=self.node_id,
                                                    new_node_id=node_id)
        self.node_id = node_id
        for dev in self.pci_devs:
            dev.compute_node_id = node_id


def get_instance_pci_devs(inst, request_id=None):
    """Get the devices allocated to one or all requests for an instance.

    - For generic PCI request, the request id is None.
    - For sr-iov networking, the request id is a valid uuid
    - There are a couple of cases where all the PCI devices allocated to an
      instance need to be returned. Refer to libvirt driver that handles
      soft_reboot and hard_boot of 'xen' instances.
    """
    pci_devices = inst.pci_devices
    return [device for device in pci_devices if
                   device.request_id == request_id or request_id == 'all']
