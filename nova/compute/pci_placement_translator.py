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

from oslo_log import log as logging

from nova.compute import provider_tree
from nova import exception
from nova.i18n import _
from nova.objects import fields
from nova.objects import pci_device
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


def _get_rc_for_dev(dev: pci_device.PciDevice) -> str:
    return f"CUSTOM_PCI_{dev.vendor_id}_{dev.product_id}"


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

    def add_child(self, dev: pci_device.PciDevice) -> None:
        rc = _get_rc_for_dev(dev)
        self.children_devs.append(dev)
        self.resource_class = rc
        self.traits = set()

    def add_parent(self, dev: pci_device.PciDevice) -> None:
        self.parent_dev = dev
        self.resource_class = _get_rc_for_dev(dev)
        self.traits = set()

    def update_provider_tree(
        self, provider_tree: provider_tree.ProviderTree
    ) -> None:
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
        return (
            f"RP({self.name}, {self.resource_class}={len(self.devs)}, "
            f"traits={','.join(self.traits or set())})"
        )


class PlacementView:
    """The PCI Placement view"""

    def __init__(self, hypervisor_hostname: str) -> None:
        self.rps: ty.Dict[str, PciResourceProvider] = {}
        self.root_rp_name = hypervisor_hostname

    def _get_rp_name_for_address(self, addr: str) -> str:
        return f"{self.root_rp_name}_{addr.upper()}"

    def _ensure_rp(self, rp_name: str) -> PciResourceProvider:
        return self.rps.setdefault(rp_name, PciResourceProvider(rp_name))

    def _add_child(self, dev: pci_device.PciDevice) -> None:
        if not dev.parent_addr:
            msg = _(
                "Missing parent address for PCI device s(dev)% with "
                "type s(type)s"
            ) % {
                "dev": dev.address,
                "type": dev.dev_type,
            }
            raise exception.PlacementPciException(error=msg)

        rp_name = self._get_rp_name_for_address(dev.parent_addr)
        self._ensure_rp(rp_name).add_child(dev)

    def _add_parent(self, dev: pci_device.PciDevice) -> None:
        rp_name = self._get_rp_name_for_address(dev.address)
        self._ensure_rp(rp_name).add_parent(dev)

    def add_dev(self, dev: pci_device.PciDevice) -> None:
        if dev.dev_type in PARENT_TYPES:
            self._add_parent(dev)
        elif dev.dev_type in CHILD_TYPES:
            self._add_child(dev)
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

    LOG.debug(
        'Collecting PCI inventories and allocations to track them in Placement'
    )

    pv = PlacementView(nodename)
    for dev in pci_tracker.pci_devs:
        pv.add_dev(dev)

    LOG.info("Placement PCI resource view: %s", pv)

    pv.update_provider_tree(provider_tree)
    # FIXME(gibi): Check allocations too based on pci_dev.instance_uuid and
    #  if here was any update then we have to return True to trigger a reshape.

    return False
