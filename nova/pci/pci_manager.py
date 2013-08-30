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

import collections

from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.objects import instance
from nova.objects import pci_device
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.pci import pci_request
from nova.pci import pci_stats
from nova.pci import pci_utils

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
        self.stats = pci_stats.PciDeviceStats()
        if node_id:
            self.pci_devs = pci_device.PciDeviceList.get_by_compute_node(
                context, node_id)
        else:
            self.pci_devs = pci_device.PciDeviceList()
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

    def _filter_devices_for_spec(self, request_spec, pci_devs):
        return [p for p in pci_devs
                if pci_utils.pci_device_prop_match(p, request_spec)]

    def _get_free_devices_for_request(self, pci_request, pci_devs):
        count = pci_request.get('count', 1)
        spec = pci_request.get('spec', [])
        devs = self._filter_devices_for_spec(spec, pci_devs)
        if len(devs) < count:
            return None
        else:
            return devs[:count]

    @property
    def free_devs(self):
        return [dev for dev in self.pci_devs if dev.status == 'available']

    def get_free_devices_for_requests(self, pci_requests):
        """Select free pci devices for requests

        Pci_requests is a list of pci_request dictionaries. Each dictionary
        has three keys:
            count: number of pci devices required, default 1
            spec: the pci properties that the devices should meet
            alias_name: alias the pci_request is translated from, optional

        If any single pci_request cannot find any free devices, then the
        entire request list will fail.
        """
        alloc = []

        for request in pci_requests:
            available = self._get_free_devices_for_request(
                request,
                [p for p in self.free_devs if p not in alloc])
            if not available:
                return []
            alloc.extend(available)
        return alloc

    @property
    def all_devs(self):
        return self.pci_devs

    def save(self, context):
        for dev in self.pci_devs:
            if dev.obj_what_changed():
                dev.save(context)

        self.pci_devs.objects = [dev for dev in self.pci_devs
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
                    existed.remove()
                except exception.PciDeviceInvalidStatus as e:
                    LOG.warn(_("Trying to remove device with %(status)s"
                        "ownership %(instance_uuid)s"), existed)
                    # Note(yjiang5): remove the device by force so that
                    # db entry is cleaned in next sync.
                    existed.status = 'removed'
                else:
                    # Note(yjiang5): no need to update stats if an assigned
                    # device is hot removed.
                    self.stats.consume_device(existed)
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
                    self.stale[dev['address']] = dev
                else:
                    existed.update_device(new_value)

        for dev in [dev for dev in devices if
                    dev['address'] in new_addrs - exist_addrs]:
            dev['compute_node_id'] = self.node_id
            dev_obj = pci_device.PciDevice.create(dev)
            self.pci_devs.objects.append(dev_obj)
            self.stats.add_device(dev_obj)

    def _claim_instance(self, instance, prefix=''):
        pci_requests = pci_request.get_instance_pci_requests(
            instance, prefix)
        if not pci_requests:
            return None
        devs = self.get_free_devices_for_requests(pci_requests)
        if not devs:
            raise exception.PciDeviceRequestFailed(pci_requests)
        for dev in devs:
            dev.claim(instance)
            self.stats.consume_device(dev)
        return devs

    def _allocate_instance(self, instance, devs):
        for dev in devs:
            dev.allocate(instance)

    def _free_device(self, dev, instance=None):
        dev.free(instance)
        stale = self.stale.pop(dev['address'], None)
        if stale:
            dev.update_device(stale)
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

    def update_pci_for_instance(self, instance):
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
            devs = self._claim_instance(instance)
            if devs:
                self._allocate_instance(instance, devs)
                self.allocations[uuid] = devs

    def update_pci_for_migration(self, instance, sign=1):
        """Update instance's pci usage information when it is migrated.

        The caller should hold the COMPUTE_RESOURCE_SEMAPHORE lock.

        :param sign: claim devices for instance when sign is 1, remove
                     the claims when sign is -1
        """
        uuid = instance['uuid']
        if sign == 1 and uuid not in self.claims:
            devs = self._claim_instance(instance, 'new_')
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
                for dev in self.claims.pop(uuid):
                    self._free_device(dev)
        for uuid in self.allocations.keys():
            if uuid not in existed:
                for dev in self.allocations.pop(uuid):
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


def get_instance_pci_devs(inst):
    """Get the devices assigned to the instances."""
    if isinstance(inst, instance.Instance):
        return inst.pci_devices
    else:
        ctxt = context.get_admin_context()
        return pci_device.PciDeviceList.get_by_instance_uuid(
            ctxt, inst['uuid'])
