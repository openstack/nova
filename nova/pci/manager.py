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
import typing as ty

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import context as ctx
from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci import stats
from nova.pci import whitelist

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

MappingType = ty.Dict[str, ty.List['objects.PciDevice']]
PCIInvType = ty.DefaultDict[str, ty.List['objects.PciDevice']]


class PciDevTracker(object):
    """Manage pci devices in a compute node.

    This class fetches pci passthrough information from hypervisor
    and tracks the usage of these devices.

    It's called by compute node resource tracker to allocate and free
    devices to/from instances, and to update the available pci passthrough
    device information from the hypervisor periodically.

    The `pci_devs` attribute of this class is the in-memory "master copy" of
    all devices on each compute host, and all data changes that happen when
    claiming/allocating/freeing devices HAVE TO be made against instances
    contained in `pci_devs` list, because they are periodically flushed to the
    DB when the save() method is called.

    It is unsafe to fetch PciDevice objects elsewhere in the code for update
    purposes as those changes will end up being overwritten when the `pci_devs`
    are saved.
    """

    def __init__(
        self,
        context: ctx.RequestContext,
        compute_node: 'objects.ComputeNode',
    ):
        """Create a pci device tracker.

        :param context: The request context.
        :param compute_node: The object.ComputeNode whose PCI devices we're
                             tracking.
        """
        self.stale: ty.Dict[str, objects.PciDevice] = {}
        self.node_id: str = compute_node.id
        self.dev_filter = whitelist.Whitelist(CONF.pci.device_spec)
        numa_topology = compute_node.numa_topology
        if numa_topology:
            # For legacy reasons, the NUMATopology is stored as a JSON blob.
            # Deserialize it into a real object.
            numa_topology = objects.NUMATopology.obj_from_db_obj(numa_topology)
        self.stats = stats.PciDeviceStats(
            numa_topology, dev_filter=self.dev_filter)
        self._context = context
        self.pci_devs = objects.PciDeviceList.get_by_compute_node(
            context, self.node_id)
        self._build_device_tree(self.pci_devs)
        self._initial_instance_usage()

    def _initial_instance_usage(self) -> None:
        self.allocations: PCIInvType = collections.defaultdict(list)
        self.claims: PCIInvType = collections.defaultdict(list)

        for dev in self.pci_devs:
            uuid = dev.instance_uuid
            if dev.status == fields.PciDeviceStatus.CLAIMED:
                self.claims[uuid].append(dev)
            elif dev.status == fields.PciDeviceStatus.ALLOCATED:
                self.allocations[uuid].append(dev)
            elif dev.status == fields.PciDeviceStatus.AVAILABLE:
                self.stats.add_device(dev)

    def save(self, context: ctx.RequestContext) -> None:
        for dev in self.pci_devs:
            if dev.obj_what_changed():
                with dev.obj_alternate_context(context):
                    dev.save()
                    if dev.status == fields.PciDeviceStatus.DELETED:
                        self.pci_devs.objects.remove(dev)

    @property
    def pci_stats(self) -> stats.PciDeviceStats:
        return self.stats

    def update_devices_from_hypervisor_resources(
        self, devices_json: str,
    ) -> None:
        """Sync the pci device tracker with hypervisor information.

        To support pci device hot plug, we sync with the hypervisor
        periodically, fetching all devices information from hypervisor,
        update the tracker and sync the DB information.

        Devices should not be hot-plugged when assigned to a guest,
        but possibly the hypervisor has no such guarantee. The best
        we can do is to give a warning if a device is changed
        or removed while assigned.

        :param devices_json: The JSON-ified string of device information
                             that is returned from the virt driver's
                             get_available_resource() call in the
                             pci_passthrough_devices key.
        """

        devices = []
        for dev in jsonutils.loads(devices_json):
            try:
                if self.dev_filter.device_assignable(dev):
                    devices.append(dev)
            except exception.PciConfigInvalidSpec as e:
                # The raised exception is misleading as the problem is not with
                # the whitelist config but with the host PCI device reported by
                # libvirt. The code that matches the host PCI device to the
                # withelist spec reuses the WhitelistPciAddress object to parse
                # the host PCI device address. That parsing can fail if the
                # PCI address has a 32 bit domain. But this should not prevent
                # processing the rest of the devices. So we simply skip this
                # device and continue.
                # Please note that this except block does not ignore the
                # invalid whitelist configuration. The whitelist config has
                # already been parsed or rejected in case it was invalid. At
                # this point the self.dev_filter representes the parsed and
                # validated whitelist config.
                LOG.debug(
                    'Skipping PCI device %s reported by the hypervisor: %s',
                    {k: v for k, v in dev.items()
                     if k in ['address', 'parent_addr']},
                    # NOTE(gibi): this is ugly but the device_assignable() call
                    # uses the PhysicalPciAddress class to parse the PCI
                    # addresses and that class reuses the code from
                    # PciAddressSpec that was originally designed to parse
                    # whitelist spec. Hence the raised exception talks about
                    # whitelist config. This is misleading as in our case the
                    # PCI address that we failed to parse came from the
                    # hypervisor.
                    # TODO(gibi): refactor the false abstraction to make the
                    # code reuse clean from the false assumption that we only
                    # parse whitelist config with
                    # devspec.PciAddressSpec._set_pci_dev_info()
                    str(e).replace(
                        'Invalid [pci]device_spec config:', 'The'))

        self._set_hvdevs(devices)

    @staticmethod
    def _build_device_tree(all_devs: ty.List['objects.PciDevice']) -> None:
        """Build a tree of devices that represents parent-child relationships.

        We need to have the relationships set up so that we can easily make
        all the necessary changes to parent/child devices without having to
        figure it out at each call site.

        This method just adds references to relevant instances already found
        in `pci_devs` to `child_devices` and `parent_device` fields of each
        one.

        Currently relationships are considered for SR-IOV PFs/VFs only.
        """

        # Ensures that devices are ordered in ASC so VFs will come
        # after their PFs.
        all_devs.sort(key=lambda x: x.address)

        parents = {}
        for dev in all_devs:
            if dev.status in (fields.PciDeviceStatus.REMOVED,
                              fields.PciDeviceStatus.DELETED):
                # NOTE(ndipanov): Removed devs are pruned from
                # self.pci_devs on save() so we need to make sure we
                # are not looking at removed ones as we may build up
                # the tree sooner than they are pruned.
                continue
            if dev.dev_type == fields.PciDeviceType.SRIOV_PF:
                dev.child_devices = []
                parents[dev.address] = dev
            elif dev.dev_type in (
                fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA
            ):
                dev.parent_device = parents.get(dev.parent_addr)
                if dev.parent_device:
                    parents[dev.parent_addr].child_devices.append(dev)

    def _set_hvdevs(self, devices: ty.List[ty.Dict[str, ty.Any]]) -> None:
        exist_addrs = set([dev.address for dev in self.pci_devs])
        new_addrs = set([dev['address'] for dev in devices])

        for existed in self.pci_devs:
            if existed.address in exist_addrs - new_addrs:
                # Remove previously tracked PCI devices that are either
                # no longer reported by the hypervisor or have been removed
                # from the pci whitelist.
                try:
                    existed.remove()
                except (
                        exception.PciDeviceInvalidStatus,
                        exception.PciDeviceInvalidOwner,
                ) as e:
                    LOG.warning("Unable to remove device with status "
                                "'%(status)s' and ownership %(instance_uuid)s "
                                "because of %(pci_exception)s. "
                                "Check your [pci]device_spec "
                                "configuration to make sure this allocated "
                                "device is whitelisted. If you have removed "
                                "the device from the whitelist intentionally "
                                "or the device is no longer available on the "
                                "host you will need to delete the server or "
                                "migrate it to another host to silence this "
                                "warning.",
                                {'status': existed.status,
                                 'instance_uuid': existed.instance_uuid,
                                 'pci_exception': e.format_message()})
                    # NOTE(sean-k-mooney): the device may not be tracked for
                    # two reasons: first the device could have been removed
                    # from the host or second the whitelist could have been
                    # updated. While force removing may seam reasonable, if
                    # the device is allocated to a vm, force removing the
                    # device entry from the resource tracker can prevent the vm
                    # from rebooting. If the PCI device was removed due to an
                    # update to the PCI whitelist which was later reverted,
                    # removing the entry from the database and adding it back
                    # later may lead to the scheduler incorrectly selecting
                    # this host and the ResourceTracker assigning the PCI
                    # device to a second vm. To prevent this bug we skip
                    # deleting the device from the db in this iteration and
                    # will try again on the next sync.
                    continue
                else:
                    # Note(yjiang5): no need to update stats if an assigned
                    # device is hot removed.
                    # NOTE(gibi): only remove the device from the pools if it
                    # is not already removed
                    if existed in self.stats.get_free_devs():
                        self.stats.remove_device(existed)
            else:
                # Update tracked devices.
                new_value: ty.Dict[str, ty.Any]
                new_value = next((dev for dev in devices if
                    dev['address'] == existed.address))
                new_value['compute_node_id'] = self.node_id
                if existed.status in (fields.PciDeviceStatus.CLAIMED,
                                      fields.PciDeviceStatus.ALLOCATED):
                    # Pci properties may change while assigned because of
                    # hotplug or config changes. Although normally this should
                    # not happen.

                    # As the devices have been assigned to an instance,
                    # we defer the change till the instance is destroyed.
                    # We will not sync the new properties with database
                    # before that.

                    # TODO(yjiang5): Not sure if this is a right policy, but
                    # at least it avoids some confusion and, if needed,
                    # we can add more action like killing the instance
                    # by force in future.
                    self.stale[new_value['address']] = new_value
                else:
                    existed.update_device(new_value)
                    self.stats.update_device(existed)

        # Track newly discovered devices.
        for dev in [dev for dev in devices if
                    dev['address'] in new_addrs - exist_addrs]:
            dev['compute_node_id'] = self.node_id
            dev_obj = objects.PciDevice.create(self._context, dev)
            self.pci_devs.objects.append(dev_obj)
            self.stats.add_device(dev_obj)

        self._build_device_tree(self.pci_devs)

    def _claim_instance(
        self,
        context: ctx.RequestContext,
        pci_requests: 'objects.InstancePCIRequests',
        instance_numa_topology: 'objects.InstanceNUMATopology',
    ) -> ty.List['objects.PciDevice']:
        instance_cells = None
        if instance_numa_topology:
            instance_cells = instance_numa_topology.cells

        devs = self.stats.consume_requests(pci_requests.requests,
                                           instance_cells)
        if not devs:
            return []

        instance_uuid = pci_requests.instance_uuid
        for dev in devs:
            dev.claim(instance_uuid)
        if instance_numa_topology and any(
                                        dev.numa_node is None for dev in devs):
            LOG.warning("Assigning a pci device without numa affinity to "
                        "instance %(instance)s which has numa topology",
                        {'instance': instance_uuid})
        return devs

    def claim_instance(
        self,
        context: ctx.RequestContext,
        pci_requests: 'objects.InstancePCIRequests',
        instance_numa_topology: 'objects.InstanceNUMATopology',
    ) -> ty.List['objects.PciDevice']:

        devs = []

        if self.pci_devs and pci_requests.requests:
            instance_uuid = pci_requests.instance_uuid
            devs = self._claim_instance(context, pci_requests,
                                        instance_numa_topology)
            if devs:
                self.claims[instance_uuid] = devs
        return devs

    def _allocate_instance(
        self, instance: 'objects.Instance', devs: ty.List['objects.PciDevice'],
    ) -> None:
        for dev in devs:
            dev.allocate(instance)

    def allocate_instance(self, instance: 'objects.Instance') -> None:
        devs = self.claims.pop(instance['uuid'], [])
        self._allocate_instance(instance, devs)
        if devs:
            self.allocations[instance['uuid']] += devs

    def free_device(
        self, dev: 'objects.PciDevice', instance: 'objects.Instance'
    ) -> None:
        """Free device from pci resource tracker

        :param dev: cloned pci device object that needs to be free
        :param instance: the instance that this pci device
                         is allocated to
        """
        for pci_dev in self.pci_devs:
            # Find the matching pci device in the pci resource tracker.
            # Once found, free it.
            if dev.id == pci_dev.id and dev.instance_uuid == instance['uuid']:
                self._remove_device_from_pci_mapping(
                    instance['uuid'], pci_dev, self.allocations)
                self._remove_device_from_pci_mapping(
                    instance['uuid'], pci_dev, self.claims)
                self._free_device(pci_dev)
                break

    def _remove_device_from_pci_mapping(
        self,
        instance_uuid: str,
        pci_device: 'objects.PciDevice',
        pci_mapping: MappingType,
    ) -> None:
        """Remove a PCI device from allocations or claims.

        If there are no more PCI devices, pop the uuid.
        """
        pci_devices = pci_mapping.get(instance_uuid, [])
        if pci_device in pci_devices:
            pci_devices.remove(pci_device)
            if len(pci_devices) == 0:
                pci_mapping.pop(instance_uuid, None)

    def _free_device(
        self, dev: 'objects.PciDevice', instance: 'objects.Instance' = None,
    ) -> None:
        freed_devs = dev.free(instance)
        stale = self.stale.pop(dev.address, None)
        if stale:
            dev.update_device(stale)
        for dev in freed_devs:
            self.stats.add_device(dev)

    def free_instance_allocations(
        self, context: ctx.RequestContext, instance: 'objects.Instance',
    ) -> None:
        """Free devices that are in ALLOCATED state for instance.

        :param context: user request context
        :param instance: instance object
        """
        if not self.allocations.pop(instance['uuid'], None):
            return

        for dev in self.pci_devs:
            if (dev.status == fields.PciDeviceStatus.ALLOCATED and
                    dev.instance_uuid == instance['uuid']):
                self._free_device(dev, instance)

    def free_instance_claims(
        self, context: ctx.RequestContext, instance: 'objects.Instance',
    ) -> None:
        """Free devices that are in CLAIMED state for instance.

        :param context: user request context (nova.context.RequestContext)
        :param instance: instance object
        """
        if not self.claims.pop(instance['uuid'], None):
            return

        for dev in self.pci_devs:
            if (dev.status == fields.PciDeviceStatus.CLAIMED and
                    dev.instance_uuid == instance['uuid']):
                self._free_device(dev, instance)

    def free_instance(
        self, context: ctx.RequestContext, instance: 'objects.Instance',
    ) -> None:
        """Free devices that are in CLAIMED or ALLOCATED state for instance.

        :param context: user request context (nova.context.RequestContext)
        :param instance: instance object
        """
        # Note(yjiang5): When an instance is resized, the devices in the
        # destination node are claimed to the instance in prep_resize stage.
        # However, the instance contains only allocated devices
        # information, not the claimed one. So we can't use
        # instance['pci_devices'] to check the devices to be freed.
        self.free_instance_allocations(context, instance)
        self.free_instance_claims(context, instance)

    def update_pci_for_instance(
        self,
        context: ctx.RequestContext,
        instance: 'objects.Instance',
        sign: int,
    ) -> None:
        """Update PCI usage information if devices are de/allocated."""
        if not self.pci_devs:
            return

        if sign == -1:
            self.free_instance(context, instance)
        if sign == 1:
            self.allocate_instance(instance)

    def clean_usage(
        self,
        instances: 'objects.InstanceList',
        migrations: 'objects.MigrationList',
    ) -> None:
        """Remove all usages for instances not passed in the parameter.

        The caller should hold the COMPUTE_RESOURCE_SEMAPHORE lock
        """
        existed = set(inst.uuid for inst in instances)
        existed |= set(mig.instance_uuid for mig in migrations)

        # need to copy keys, because the dict is modified in the loop body
        for uuid in list(self.claims):
            if uuid not in existed:
                devs = self.claims.pop(uuid, [])
                for dev in devs:
                    self._free_device(dev)
        # need to copy keys, because the dict is modified in the loop body
        for uuid in list(self.allocations):
            if uuid not in existed:
                devs = self.allocations.pop(uuid, [])
                for dev in devs:
                    self._free_device(dev)
