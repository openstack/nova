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
import copy
import typing as ty

import os_resource_classes
import os_traits
from oslo_log import log as logging
from oslo_utils import uuidutils

from nova.compute import provider_tree
import nova.conf
from nova import exception
from nova.i18n import _
from nova.objects import fields
from nova.objects import pci_device
from nova.pci import devspec
from nova.pci import manager as pci_manager


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


# Devs with this type are in one to one mapping with an RP in placement
PARENT_TYPES = (
    fields.PciDeviceType.STANDARD, fields.PciDeviceType.SRIOV_PF)
# Devs with these type need to have a parent and that parent is the one
# that mapped  to a placement RP
CHILD_TYPES = (
    fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA)


def _is_placement_tracking_enabled() -> bool:
    return CONF.pci.report_in_placement


def _normalize_traits(traits: ty.List[str]) -> ty.List[str]:
    """Make the trait names acceptable for placement.

    It keeps the already valid standard or custom traits but normalizes trait
    names that are not already normalized.
    """
    standard_traits, rest = os_traits.check_traits(traits)
    custom_traits = []
    for name in rest:
        name = name.upper()
        if os_traits.is_custom(name):
            custom_traits.append(name)
        else:
            custom_traits.append(os_traits.normalize_name(name))

    return list(standard_traits) + custom_traits


def get_traits(traits_str: str) -> ty.Set[str]:
    """Return a normalized set of placement standard and custom traits from
    a string of comma separated trait names.
    """
    # traits is a comma separated list of placement trait names
    if not traits_str:
        return set()
    return set(_normalize_traits(traits_str.split(',')))


def _get_traits_for_dev(
    dev_spec_tags: ty.Dict[str, str],
) -> ty.Set[str]:
    return get_traits(dev_spec_tags.get("traits", "")) | {
        os_traits.COMPUTE_MANAGED_PCI_DEVICE
    }


def _normalize_resource_class(rc: str) -> str:
    rc = rc.upper()
    if (
            rc not in os_resource_classes.STANDARDS and
            not os_resource_classes.is_custom(rc)
    ):
        rc = os_resource_classes.normalize_name(rc)
        # mypy: normalize_name will return non None for non None input
        assert rc

    return rc


def get_resource_class(
    requested_name: ty.Optional[str], vendor_id: str, product_id: str
) -> str:
    """Return the normalized resource class name based on what is requested
    or if nothing is requested then generated from the vendor_id and product_id
    """
    if requested_name:
        rc = _normalize_resource_class(requested_name)
    else:
        rc = f"CUSTOM_PCI_{vendor_id}_{product_id}".upper()
    return rc


def _get_rc_for_dev(
    dev: pci_device.PciDevice,
    dev_spec_tags: ty.Dict[str, str],
) -> str:
    """Return the resource class to represent the device.

    It is either provided by the user in the configuration as the
    resource_class tag, or we are generating one from vendor_id and product_id.

    The user specified resource class is normalized if it is not already an
    acceptable standard or custom resource class.
    """
    rc = dev_spec_tags.get("resource_class")
    return get_resource_class(rc, dev.vendor_id, dev.product_id)


class PciResourceProvider:
    """A PCI Resource Provider"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.parent_dev = None
        self.children_devs: ty.List[pci_device.PciDevice] = []
        self.resource_class: ty.Optional[str] = None
        self.traits: ty.Optional[ty.Set[str]] = None
        # This is an adjustment for the total inventory based on normal device
        # due to possibility of devices held in the tracker even though they
        # are removed from the configuration due to still having allocations.
        # This number will be calculated based on the existing allocations
        # during update_provider_tree call.
        self.adjustment = 0

    @property
    def devs(self) -> ty.List[pci_device.PciDevice]:
        return [self.parent_dev] if self.parent_dev else self.children_devs

    @property
    def total(self):
        return len(self.devs) + self.adjustment

    @property
    def to_be_deleted(self):
        return self.total == 0

    def add_child(self, dev, dev_spec_tags: ty.Dict[str, str]) -> None:
        if self.parent_dev:
            raise exception.PlacementPciDependentDeviceException(
                parent_dev=dev.address,
                children_devs=",".join(dev.address for dev in self.devs)
            )

        rc = _get_rc_for_dev(dev, dev_spec_tags)
        if self.resource_class and rc != self.resource_class:
            raise exception.PlacementPciMixedResourceClassException(
                new_rc=rc,
                new_dev=dev.address,
                current_rc=self.resource_class,
                current_devs=",".join(
                    dev.address for dev in self.children_devs)
            )

        traits = _get_traits_for_dev(dev_spec_tags)
        if self.traits is not None and self.traits != traits:
            raise exception.PlacementPciMixedTraitsException(
                new_traits=",".join(sorted(traits)),
                new_dev=dev.address,
                current_traits=",".join(sorted(self.traits)),
                current_devs=",".join(
                    dev.address for dev in self.children_devs),
            )

        self.children_devs.append(dev)
        self.resource_class = rc
        self.traits = traits

    def add_parent(self, dev, dev_spec_tags: ty.Dict[str, str]) -> None:
        if self.parent_dev or self.children_devs:
            raise exception.PlacementPciDependentDeviceException(
                parent_dev=dev.address,
                children_devs=",".join(dev.address for dev in self.devs)
            )

        self.parent_dev = dev
        self.resource_class = _get_rc_for_dev(dev, dev_spec_tags)
        self.traits = _get_traits_for_dev(dev_spec_tags)

    def remove_child(self, dev: pci_device.PciDevice) -> None:
        # Nothing to do here. The update_provider_tree will handle the
        # inventory decrease or the full RP removal
        pass

    def remove_parent(self, dev: pci_device.PciDevice) -> None:
        # Nothing to do here. The update_provider_tree we handle full RP
        pass

    def _get_allocations(self) -> ty.Mapping[str, int]:
        """Return a dict of used resources keyed by consumer UUID.

        Note that:
        1) a single consumer can consume more than one resource from a single
           RP. I.e. A VM with two VFs from the same parent PF
        2) multiple consumers can consume resources from a single RP. I.e. two
           VMs consuming one VF from the same PF each
        3) regardless of how many consumers we have on a single PCI RP, they
           are always consuming resources from the same resource class as
           we are not supporting dependent devices modelled by the same RP but
           different resource classes.
        """
        return collections.Counter(
            [
                dev.instance_uuid
                for dev in self.devs
                if "instance_uuid" in dev and dev.instance_uuid
            ]
        )

    def _adjust_for_removals_and_held_devices(
        self,
        provider_tree: provider_tree.ProviderTree,
        rp_rc_usage: ty.Dict[str, ty.Dict[str, int]],
    ) -> None:

        rp_uuid = provider_tree.data(self.name).uuid
        rc_usage = rp_rc_usage[rp_uuid]

        if not self.resource_class:
            # The resource_class is undefined when there are no normal devices
            # exists any more on this RP. If no normal devs exists then there
            # is no device_spec to derive the RC and traits from. But if we
            # still have allocations in placement against this RP that means
            # there are devices removed from the configuration but kept in the
            # tracker as they are still allocated. In this case we
            # need to recover the resource class and traits from the
            # existing allocation.
            if len(rc_usage) == 0:
                # no usage so nothing to adjust here
                return
            else:
                # The len > 1 case should not happen for PCI RPs as we either
                # track the parent PF or the child VFs there on the RP but
                # never both.
                self.resource_class = list(rc_usage.keys())[0]
                self.traits = provider_tree.data(rp_uuid).traits

        # If device being removed but still held due to still having
        # allocations then we need to adjust the total inventory to never go
        # below the current usage otherwise Placement will reject the update.
        usage = rc_usage[self.resource_class]
        inventory = self.total
        if usage > inventory:
            LOG.warning(
                "Needed to adjust inventories of %s on "
                "resource provider %s from %d to %d due to existing "
                "placement allocations. This should only happen while "
                "VMs using already removed devices.",
                self.resource_class, self.name, inventory, usage)
            # This is counted into self.total to adjust the inventory
            self.adjustment += usage - inventory

    def update_provider_tree(
        self,
        provider_tree: provider_tree.ProviderTree,
        parent_rp_name: str,
        rp_rc_usage: ty.Dict[str, ty.Dict[str, int]],
    ) -> None:

        if not provider_tree.exists(self.name):
            # NOTE(gibi): We need to generate UUID for the new provider in Nova
            # instead of letting Placement assign one. We are potentially
            # healing a missing RP along with missing allocations on that RP.
            # The allocation healing happens with POST /reshape, and that API
            # only takes RP UUIDs.
            provider_tree.new_child(
                self.name,
                parent_rp_name,
                uuid=uuidutils.generate_uuid(dashed=True)
            )

        self._adjust_for_removals_and_held_devices(provider_tree, rp_rc_usage)

        # if after the adjustment no inventory left then we need to delete
        # the RP explicitly
        if self.total == 0:
            provider_tree.remove(self.name)
            return

        provider_tree.update_inventory(
            self.name,
            # NOTE(gibi): The rest of the inventory fields (reserved,
            # allocation_ratio, etc.) are defaulted by placement and the
            # default value make sense for PCI devices, i.e. no overallocation
            # and PCI can be allocated one by one.
            # Also, this way if the operator sets reserved value in placement
            # for the PCI inventories directly then nova will not override that
            # value periodically.
            {
                self.resource_class: {
                    "total": self.total,
                    "max_unit": self.total,
                }
            },
        )
        provider_tree.update_traits(self.name, self.traits)

        # Here we are sure the RP exists in the provider_tree. So, we can
        # record the RP UUID in each PciDevice this RP represents
        rp_uuid = provider_tree.data(self.name).uuid
        for dev in self.devs:
            dev.extra_info['rp_uuid'] = rp_uuid

    def update_allocations(
        self,
        allocations: dict,
        provider_tree: provider_tree.ProviderTree,
        same_host_instances: ty.List[str],
    ) -> bool:
        updated = False

        if self.to_be_deleted:
            # the RP is going away because either removed from the hypervisor
            # or the compute's config is changed to ignore the device.
            return updated

        # we assume here that if this RP has been created in the current round
        # of healing then it already has a UUID assigned.
        rp_uuid = provider_tree.data(self.name).uuid

        for consumer, amount in self._get_allocations().items():
            if consumer not in allocations:
                # We have PCI device(s) allocated to an instance, but we don't
                # see any instance allocation in placement. This
                # happens for two reasons:
                # 1) The instance is being migrated and therefore the
                #    allocation is held by the migration UUID in placement. In
                #    this case the PciDevice is still allocated to the instance
                #    UUID in the nova DB hence our lookup for the instance
                #    allocation here. We can ignore this case as: i) We healed
                #    the PCI allocation for the instance before the migration
                #    was started. ii) Nova simply moves the allocation from the
                #    instance UUID to the migration UUID in placement. So we
                #    assume the migration allocation is correct without
                #    healing. One limitation of this is that if there is in
                #    progress migration when nova is upgraded, then the PCI
                #    allocation of that migration will be missing from
                #    placement on the source host. But it is temporary and the
                #    allocation will be fixed as soon as the migration is
                #    completed or reverted.
                # 2) We have a bug in the scheduler or placement and the whole
                #    instance allocation is lost. We cannot handle that here.
                #    It is expected to be healed via nova-manage placement
                #    heal_allocation CLI instead.
                continue

            if consumer in same_host_instances:
                # This is a nasty special case. This instance is undergoing
                # a same host resize. So in Placement the source host
                # allocation is held by the migration UUID *but* the
                # PciDevice.instance_uuid is set for the instance UUID both
                # on the source and on the destination host. As the source and
                # dest are the same for migration we will see PciDevice
                # objects assigned to this instance that should not be
                # allocated to the instance UUID in placement.
                # As noted above we don't want to take care in progress
                # migration during healing. So we simply ignore this instance.
                # If the instance needs healing then it will be healed when
                # after the migration is confirmed or reverted.
                continue

            current_allocs = allocations[consumer]['allocations']
            current_rp_allocs = current_allocs.get(rp_uuid)

            if current_rp_allocs:
                # update an existing allocation if the current one differs
                current_rc_allocs = current_rp_allocs["resources"].get(
                    self.resource_class, 0)
                if current_rc_allocs != amount:
                    current_rp_allocs[
                        "resources"][self.resource_class] = amount
                    updated = True
            else:
                # insert a new allocation as it is missing
                current_allocs[rp_uuid] = {
                    "resources": {self.resource_class: amount}
                }
                updated = True

        return updated

    def __str__(self) -> str:
        if not self.to_be_deleted:
            return (
                f"RP({self.name}, {self.resource_class}={self.total}, "
                f"traits={','.join(sorted(self.traits or set()))})"
            )
        else:
            return f"RP({self.name}, <to be deleted>)"


class PlacementView:
    """The PCI Placement view"""

    def __init__(
        self,
        hypervisor_hostname: str,
        instances_under_same_host_resize: ty.List[str],
    ) -> None:
        self.rps: ty.Dict[str, PciResourceProvider] = {}
        self.root_rp_name = hypervisor_hostname
        self.same_host_instances = instances_under_same_host_resize

    def _get_rp_name_for_address(self, addr: str) -> str:
        return f"{self.root_rp_name}_{addr.upper()}"

    def _ensure_rp(self, rp_name: str) -> PciResourceProvider:
        return self.rps.setdefault(rp_name, PciResourceProvider(rp_name))

    def _get_rp_name_for_child(self, dev: pci_device.PciDevice) -> str:
        if not dev.parent_addr:
            msg = _(
                "Missing parent address for PCI device s(dev)% with "
                "type s(type)s"
            ) % {
                "dev": dev.address,
                "type": dev.dev_type,
            }
            raise exception.PlacementPciException(error=msg)

        return self._get_rp_name_for_address(dev.parent_addr)

    def _add_dev(
        self, dev: pci_device.PciDevice, dev_spec_tags: ty.Dict[str, str]
    ) -> None:
        if dev_spec_tags.get("physical_network"):
            # NOTE(gibi): We ignore devices that has physnet configured as
            # those are there for Neutron based SRIOV and that is out of scope
            # for now. Later these devices will be tracked as PCI_NETDEV
            # devices in placement.
            return

        rp = self._ensure_rp_for_dev(dev)
        if dev.dev_type in PARENT_TYPES:
            rp.add_parent(dev, dev_spec_tags)
        elif dev.dev_type in CHILD_TYPES:
            rp.add_child(dev, dev_spec_tags)
        else:
            msg = _(
                "Unhandled PCI device type %(type)s for %(dev)s. Please "
                "report a bug."
            ) % {
                "type": dev.dev_type,
                "dev": dev.address,
            }
            raise exception.PlacementPciException(error=msg)

    def _remove_dev(self, dev: pci_device.PciDevice) -> None:
        """Remove PCI devices from Placement that existed before but now
        deleted from the hypervisor or unlisted from [pci]device_spec
        """
        rp = self._ensure_rp_for_dev(dev)
        if dev.dev_type in PARENT_TYPES:
            rp.remove_parent(dev)
        elif dev.dev_type in CHILD_TYPES:
            rp.remove_child(dev)

    def _ensure_rp_for_dev(
        self, dev: pci_device.PciDevice
    ) -> PciResourceProvider:
        """Ensures that the RP exists for the device and returns it
        but does not do any inventory accounting for the given device on
        the RP.
        """
        if dev.dev_type in PARENT_TYPES:
            rp_name = self._get_rp_name_for_address(dev.address)
            return self._ensure_rp(rp_name)
        elif dev.dev_type in CHILD_TYPES:
            rp_name = self._get_rp_name_for_child(dev)
            return self._ensure_rp(rp_name)
        else:
            raise ValueError(
                f"Unhandled PCI device type {dev.dev_type} "
                f"for dev {dev.address}.")

    def process_dev(
        self,
        dev: pci_device.PciDevice,
        dev_spec: ty.Optional[devspec.PciDeviceSpec],
    ) -> None:
        # NOTE(gibi): We never observer dev.status DELETED as when that is set
        # the device is also removed from the PCI tracker. So we can ignore
        # that state.
        if dev.status == fields.PciDeviceStatus.REMOVED:
            # NOTE(gibi): We need to handle the situation when an instance
            # uses a device where a dev_spec is removed. Here we need to keep
            # the device in the Placement view similarly how the PCI tracker
            # does it.
            # However, we also need to handle the situation when such VM is
            # being deleted. In that case we are called after the dev is freed
            # and marked as removed by the tracker so dev.instance_uuid is
            # None and dev.status is REMOVED. At this point the Placement
            # allocation for this dev is still not deleted so we still have to
            # keep the device in our view. The device will be deleted when the
            # PCI tracker is saved which happens after us.
            # However, we cannot overly eagerly keep devices here as a
            # device in REMOVED state might be a device that had no allocation
            # in Placement so it can be removed already without waiting for
            # the next periodic update when the device disappears from the
            # PCI tracker's list. If we are over eagerly keeping such device
            # when it is not allocated then that will prevent a single step
            # reconfiguration from whitelisting a VF to whitelisting its
            # parent PF, because the VF will be kept at restart and conflict
            # with the PF being added.

            # We choose to remove these devs so the happy path of removing
            # not allocated devs is simple. And then we do an extra
            # step later in update_provider_tree to reconcile Placement
            # allocations with our view and add back some inventories to handle
            # removed but allocated devs.
            self._remove_dev(dev)
        else:
            if not dev_spec:
                if dev.instance_uuid:
                    LOG.warning(
                        "Device spec is not found for device %s in "
                        "[pci]device_spec. The device is allocated by "
                        "%s. We are keeping this device in the Placement "
                        "view. You should not remove an allocated device from "
                        "the configuration. Please restore the configuration. "
                        "If you cannot restore the configuration as the "
                        "device is dead then delete or cold migrate the "
                        "instance and then restart the nova-compute service "
                        "to resolve the inconsistency.",
                        dev.address,
                        dev.instance_uuid
                    )
                    # We need to keep the RP, but we cannot just use _add_dev
                    # to generate the inventory on the RP as that would require
                    # to know the dev_spec to e.g. have the RC. So we only
                    # ensure that the RP exists, the inventory will be adjusted
                    # based on the existing allocation in a later step.
                    self._ensure_rp_for_dev(dev)
                else:
                    LOG.warning(
                        "Device spec is not found for device %s in "
                        "[pci]device_spec. Ignoring device in Placement "
                        "resource view. This should not happen. Please file a "
                        "bug.",
                        dev.address
                    )

                return

            self._add_dev(dev, dev_spec.get_tags())

    def __str__(self) -> str:
        return (
            f"Placement PCI view on {self.root_rp_name}: "
            f"{', '.join(str(rp) for rp in self.rps.values())}"
        )

    @staticmethod
    def get_usage_per_rc_and_rp(
        allocations
    ) -> ty.Dict[str, ty.Dict[str, int]]:
        """Returns a dict keyed by RP uuid and the value is a dict of
        resource class: usage pairs telling how much total usage the given RP
        has from the given resource class across all the allocations.
        """
        rp_rc_usage: ty.Dict[str, ty.Dict[str, int]] = (
            collections.defaultdict(lambda: collections.defaultdict(int)))
        for consumer in allocations.values():
            for rp_uuid, alloc in consumer["allocations"].items():
                for rc, amount in alloc["resources"].items():
                    rp_rc_usage[rp_uuid][rc] += amount

        return rp_rc_usage

    def _remove_managed_rps_from_tree_not_in_view(
        self, provider_tree: provider_tree.ProviderTree
    ) -> None:
        """Removes PCI RPs from the provider_tree that are not present in the
        current PlacementView.
        """
        rp_names_in_view = {rp.name for rp in self.rps.values()}
        uuids_in_tree = provider_tree.get_provider_uuids_in_tree(
            self.root_rp_name)
        for rp_uuid in uuids_in_tree:
            rp_data = provider_tree.data(rp_uuid)
            is_pci_rp = provider_tree.has_traits(
                rp_uuid, [os_traits.COMPUTE_MANAGED_PCI_DEVICE])
            if is_pci_rp and rp_data.name not in rp_names_in_view:
                provider_tree.remove(rp_uuid)

    def update_provider_tree(
        self,
        provider_tree: provider_tree.ProviderTree,
        allocations: dict,
    ) -> None:
        self._remove_managed_rps_from_tree_not_in_view(provider_tree)

        rp_rc_usage = self.get_usage_per_rc_and_rp(allocations)
        for rp_name, rp in self.rps.items():
            rp.update_provider_tree(
                provider_tree, self.root_rp_name, rp_rc_usage)

    def update_allocations(
        self,
        allocations: dict,
        provider_tree: provider_tree.ProviderTree
    ) -> bool:
        """Updates the passed in allocations dict inplace with any PCI
        allocations that is inferred from the PciDevice objects already added
        to the view. It returns True if the allocations dict has been changed,
        False otherwise.
        """
        updated = False
        for rp in self.rps.values():
            updated |= rp.update_allocations(
                allocations,
                provider_tree,
                self.same_host_instances,
            )
        return updated


def ensure_no_dev_spec_with_devname(dev_specs: ty.List[devspec.PciDeviceSpec]):
    for dev_spec in dev_specs:
        if dev_spec.dev_spec_conf.get("devname"):
            msg = _(
                "Invalid [pci]device_spec configuration. PCI Placement "
                "reporting does not support 'devname' based device "
                "specification but we got %(dev_spec)s. "
                "Please use PCI address in the configuration instead."
            ) % {"dev_spec": dev_spec.dev_spec_conf}
            raise exception.PlacementPciException(error=msg)


def ensure_tracking_was_not_enabled_before(
    provider_tree: provider_tree.ProviderTree
) -> None:
    # If placement tracking was enabled before then we do not support
    # disabling it later. To check for that we can look for RPs with
    # the COMPUTE_MANAGED_PCI_DEVICE trait. If any then we raise to
    # kill the service
    for rp_uuid in provider_tree.get_provider_uuids():
        if (
            os_traits.COMPUTE_MANAGED_PCI_DEVICE
            in provider_tree.data(rp_uuid).traits
        ):
            msg = _(
                "The [pci]report_in_placement is False but it was enabled "
                "before on this compute. Nova does not support disabling "
                "it after it is enabled."
            )
            raise exception.PlacementPciException(error=msg)


def update_provider_tree_for_pci(
    provider_tree: provider_tree.ProviderTree,
    nodename: str,
    pci_tracker: pci_manager.PciDevTracker,
    allocations: dict,
    instances_under_same_host_resize: ty.List[str],
) -> bool:
    """Based on the PciDevice objects in the pci_tracker it calculates what
    inventories and allocations needs to exist in placement and create the
    missing peaces.

    It returns True if not just the provider_tree but also allocations needed
    to be changed.

    :param allocations:
            Dict of allocation data of the form:
              { $CONSUMER_UUID: {
                    # The shape of each "allocations" dict below is identical
                    # to the return from GET /allocations/{consumer_uuid}
                    "allocations": {
                        $RP_UUID: {
                            "generation": $RP_GEN,
                            "resources": {
                                $RESOURCE_CLASS: $AMOUNT,
                                ...
                            },
                        },
                        ...
                    },
                    "project_id": $PROJ_ID,
                    "user_id": $USER_ID,
                    "consumer_generation": $CONSUMER_GEN,
                },
                ...
              }
    :param instances_under_same_host_resize: A list of instance UUIDs that
        are undergoing same host resize on this host.
    """
    if not _is_placement_tracking_enabled():
        ensure_tracking_was_not_enabled_before(provider_tree)
        # If tracking is not enabled we just return without touching anything
        return False

    ensure_no_dev_spec_with_devname(pci_tracker.dev_filter.specs)

    LOG.debug(
        'Collecting PCI inventories and allocations to track them in Placement'
    )

    pv = PlacementView(nodename, instances_under_same_host_resize)
    for dev in pci_tracker.pci_devs:
        # match the PCI device with the [pci]dev_spec config to access
        # the configuration metadata tags
        dev_spec = pci_tracker.dev_filter.get_devspec(dev)
        pv.process_dev(dev, dev_spec)

    pv.update_provider_tree(provider_tree, allocations)

    LOG.info("Placement PCI resource view: %s", pv)

    old_alloc = copy.deepcopy(allocations)
    # update_provider_tree correlated the PciDevice objects with RPs in
    # placement and recorded the RP UUID in the PciDevice object. We need to
    # trigger an update on the device pools in the tracker to get the device
    # RP UUID mapped to the device pools
    pci_tracker.stats.populate_pools_metadata_from_assigned_devices()
    updated = pv.update_allocations(allocations, provider_tree)

    if updated:
        LOG.debug(
            "Placement PCI view needs allocation healing. This should only "
            "happen if [filter_scheduler]pci_in_placement is still disabled. "
            "Original allocations: %s New allocations: %s",
            old_alloc,
            allocations,
        )

    return updated
