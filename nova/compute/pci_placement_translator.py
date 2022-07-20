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
import typing as ty

import os_resource_classes
import os_traits
from oslo_log import log as logging

from nova.compute import provider_tree
from nova import exception
from nova.i18n import _
from nova.objects import fields
from nova.objects import pci_device
from nova.pci import devspec
from nova.pci import manager as pci_manager


LOG = logging.getLogger(__name__)


# Devs with this type are in one to one mapping with an RP in placement
PARENT_TYPES = (
    fields.PciDeviceType.STANDARD, fields.PciDeviceType.SRIOV_PF)
# Devs with these type need to have a parent and that parent is the one
# that mapped  to a placement RP
CHILD_TYPES = (
    fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA)


def _is_placement_tracking_enabled() -> bool:
    # This is false to act as a feature flag while we develop the feature
    # step by step. It will be replaced with a config check when the feature is
    # ready for production.
    #
    # return CONF.pci.report_in_placement

    # Test code will mock this function to enable the feature in the test env
    return False


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


def _get_traits_for_dev(
    dev_spec_tags: ty.Dict[str, str],
) -> ty.Set[str]:
    # traits is a comma separated list of placement trait names
    traits_str = dev_spec_tags.get("traits")
    if not traits_str:
        return set()

    traits = traits_str.split(',')
    return set(_normalize_traits(traits))


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
    # Either use the resource class from the config or the vendor_id and
    # product_id of the device to generate the RC
    rc = dev_spec_tags.get("resource_class")
    if rc:
        rc = rc.upper()
        if (
            rc not in os_resource_classes.STANDARDS and
            not os_resource_classes.is_custom(rc)
        ):
            rc = os_resource_classes.normalize_name(rc)
            # mypy: normalize_name will return non None for non None input
            assert rc

    else:
        rc = f"CUSTOM_PCI_{dev.vendor_id}_{dev.product_id}".upper()

    return rc


class PciResourceProvider:
    """A PCI Resource Provider"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.parent_dev = None
        self.children_devs: ty.List[pci_device.PciDevice] = []
        self.resource_class: ty.Optional[str] = None
        self.traits: ty.Optional[ty.Set[str]] = None

    @property
    def devs(self) -> ty.List[pci_device.PciDevice]:
        return [self.parent_dev] if self.parent_dev else self.children_devs

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

    def update_provider_tree(
        self, provider_tree: provider_tree.ProviderTree
    ) -> None:

        if not self.parent_dev and not self.children_devs:
            # This means we need to delete the RP from placement if exists
            if provider_tree.exists(self.name):
                # NOTE(gibi): If there are allocations on this RP then
                # Placement will reject the update the provider_tree is
                # synced up.
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
                    "total": len(self.devs),
                    "max_unit": len(self.devs),
                }
            },
        )
        provider_tree.update_traits(self.name, self.traits)

    def __str__(self) -> str:
        if self.devs:
            return (
                f"RP({self.name}, {self.resource_class}={len(self.devs)}, "
                f"traits={','.join(self.traits or set())})"
            )
        else:
            return f"RP({self.name}, <EMPTY>)"


class PlacementView:
    """The PCI Placement view"""

    def __init__(self, hypervisor_hostname: str) -> None:
        self.rps: ty.Dict[str, PciResourceProvider] = {}
        self.root_rp_name = hypervisor_hostname

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

    def _add_child(
        self, dev: pci_device.PciDevice, dev_spec_tags: ty.Dict[str, str]
    ) -> None:
        rp_name = self._get_rp_name_for_child(dev)
        self._ensure_rp(rp_name).add_child(dev, dev_spec_tags)

    def _add_parent(
        self, dev: pci_device.PciDevice, dev_spec_tags: ty.Dict[str, str]
    ) -> None:
        rp_name = self._get_rp_name_for_address(dev.address)
        self._ensure_rp(rp_name).add_parent(dev, dev_spec_tags)

    def _add_dev(
        self, dev: pci_device.PciDevice, dev_spec_tags: ty.Dict[str, str]
    ) -> None:
        if dev_spec_tags.get("physical_network"):
            # NOTE(gibi): We ignore devices that has physnet configured as
            # those are there for Neutron based SRIOV and that is out of scope
            # for now. Later these devices will be tracked as PCI_NETDEV
            # devices in placement.
            return

        if dev.dev_type in PARENT_TYPES:
            self._add_parent(dev, dev_spec_tags)
        elif dev.dev_type in CHILD_TYPES:
            self._add_child(dev, dev_spec_tags)
        else:
            msg = _(
                "Unhandled PCI device type %(type)s for %(dev)s. Please "
                "report a bug."
            ) % {
                "type": dev.dev_type,
                "dev": dev.address,
            }
            raise exception.PlacementPciException(error=msg)

        if 'instance_uuid' in dev and dev.instance_uuid:
            # The device is allocated to an instance, so we need to make sure
            # the device will be allocated to the instance in placement too
            # FIXME(gibi): During migration the source host allocation should
            # be tight to the migration_uuid as consumer in placement. But
            # the PciDevice.instance_uuid is still pointing to the
            # instance_uuid both on the source and the dest. So we need to
            # check for running migrations.
            pass

    def _remove_child(self, dev: pci_device.PciDevice) -> None:
        rp_name = self._get_rp_name_for_child(dev)
        self._ensure_rp(rp_name).remove_child(dev)

    def _remove_parent(self, dev: pci_device.PciDevice) -> None:
        rp_name = self._get_rp_name_for_address(dev.address)
        self._ensure_rp(rp_name).remove_parent(dev)

    def _remove_dev(self, dev: pci_device.PciDevice) -> None:
        """Remove PCI devices from Placement that existed before but now
        deleted from the hypervisor or unlisted from [pci]device_spec
        """
        if dev.dev_type in PARENT_TYPES:
            self._remove_parent(dev)
        elif dev.dev_type in CHILD_TYPES:
            self._remove_child(dev)

    def process_dev(
        self,
        dev: pci_device.PciDevice,
        dev_spec: ty.Optional[devspec.PciDeviceSpec],
    ) -> None:

        if dev.status in (
            fields.PciDeviceStatus.DELETED,
            fields.PciDeviceStatus.REMOVED,
        ):
            self._remove_dev(dev)
        else:
            if not dev_spec:
                LOG.warning(
                    "Device spec is not found for device %s in "
                    "[pci]device_spec. Ignoring device in Placement resource "
                    "view. This should not happen. Please file a bug.",
                    dev.address
                )
                return

            self._add_dev(dev, dev_spec.get_tags())

    def __str__(self) -> str:
        return (
            f"Placement PCI view on {self.root_rp_name}: "
            f"{', '.join(str(rp) for rp in self.rps.values())}"
        )

    def update_provider_tree(
        self, provider_tree: provider_tree.ProviderTree
    ) -> None:
        for rp_name, rp in self.rps.items():
            if not provider_tree.exists(rp_name):
                provider_tree.new_child(rp_name, self.root_rp_name)

            rp.update_provider_tree(provider_tree)


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


def update_provider_tree_for_pci(
    provider_tree: provider_tree.ProviderTree,
    nodename: str,
    pci_tracker: pci_manager.PciDevTracker,
    allocations: dict,
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
    """
    if not _is_placement_tracking_enabled():
        # If tracking is not enabled we just return without touching anything
        return False

    ensure_no_dev_spec_with_devname(pci_tracker.dev_filter.specs)

    LOG.debug(
        'Collecting PCI inventories and allocations to track them in Placement'
    )

    pv = PlacementView(nodename)
    for dev in pci_tracker.pci_devs:
        # match the PCI device with the [pci]dev_spec config to access
        # the configuration metadata tags
        dev_spec = pci_tracker.dev_filter.get_devspec(dev)
        pv.process_dev(dev, dev_spec)

    LOG.info("Placement PCI resource view: %s", pv)

    pv.update_provider_tree(provider_tree)
    # FIXME(gibi): Check allocations too based on pci_dev.instance_uuid and
    #  if here was any update then we have to return True to trigger a reshape.

    return False
