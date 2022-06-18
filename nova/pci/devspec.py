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

import abc
import copy
import re
import string
import typing as ty

from nova import exception
from nova.i18n import _
from nova import objects
from nova.pci.request import PCI_REMOTE_MANAGED_TAG
from nova.pci import utils
from oslo_log import log as logging
from oslo_utils import strutils

MAX_VENDOR_ID = 0xFFFF
MAX_PRODUCT_ID = 0xFFFF
MAX_FUNC = 0x7
MAX_DOMAIN = 0xFFFF
MAX_BUS = 0xFF
MAX_SLOT = 0x1F
ANY = '*'
REGEX_ANY = '.*'

LOG = logging.getLogger(__name__)

PCISpecAddressType = ty.Union[ty.Dict[str, str], str]


class PciAddressSpec(metaclass=abc.ABCMeta):
    """Abstract class for all PCI address spec styles

    This class checks the address fields of the pci.device_spec
    """

    def __init__(self, pci_addr: str) -> None:
        self.domain = ''
        self.bus = ''
        self.slot = ''
        self.func = ''

    @abc.abstractmethod
    def match(self, pci_addr):
        pass

    def is_single_address(self) -> bool:
        return all([
            all(c in string.hexdigits for c in self.domain),
            all(c in string.hexdigits for c in self.bus),
            all(c in string.hexdigits for c in self.slot),
            all(c in string.hexdigits for c in self.func)])

    def _set_pci_dev_info(
        self, prop: str, maxval: int, hex_value: str
    ) -> None:
        a = getattr(self, prop)
        if a == ANY:
            return
        try:
            v = int(a, 16)
        except ValueError:
            raise exception.PciConfigInvalidSpec(
                reason=_("property %(property)s ('%(attr)s') does not parse "
                         "as a hex number.") % {'property': prop, 'attr': a})
        if v > maxval:
            raise exception.PciConfigInvalidSpec(
                reason=_("property %(property)s (%(attr)s) is greater than "
                         "the maximum allowable value (%(max)X).") %
                         {'property': prop, 'attr': a, 'max': maxval})
        setattr(self, prop, hex_value % v)


class PhysicalPciAddress(PciAddressSpec):
    """Manages the address fields for a fully-qualified PCI address.

    This function class will validate the address fields for a single
    PCI device.
    """

    def __init__(self, pci_addr: PCISpecAddressType) -> None:
        try:
            # TODO(stephenfin): Is this ever actually a string?
            if isinstance(pci_addr, dict):
                self.domain = pci_addr['domain']
                self.bus = pci_addr['bus']
                self.slot = pci_addr['slot']
                self.func = pci_addr['function']
            else:
                self.domain, self.bus, self.slot, self.func = (
                    utils.get_pci_address_fields(pci_addr))
            self._set_pci_dev_info('func', MAX_FUNC, '%1x')
            self._set_pci_dev_info('domain', MAX_DOMAIN, '%04x')
            self._set_pci_dev_info('bus', MAX_BUS, '%02x')
            self._set_pci_dev_info('slot', MAX_SLOT, '%02x')
        except (KeyError, ValueError):
            raise exception.PciDeviceWrongAddressFormat(address=pci_addr)

    def match(self, phys_pci_addr: PciAddressSpec) -> bool:
        conditions = [
            self.domain == phys_pci_addr.domain,
            self.bus == phys_pci_addr.bus,
            self.slot == phys_pci_addr.slot,
            self.func == phys_pci_addr.func,
            ]
        return all(conditions)

    def __str__(self):
        return f'{self.domain}:{self.bus}:{self.slot}.{self.func}'


class PciAddressGlobSpec(PciAddressSpec):
    """Manages the address fields with glob style.

    This function class will validate the address fields with glob style,
    check for wildcards, and insert wildcards where the field is left blank.
    """

    def __init__(self, pci_addr: str) -> None:
        self.domain = ANY
        self.bus = ANY
        self.slot = ANY
        self.func = ANY

        dbs, sep, func = pci_addr.partition('.')
        if func:
            self.func = func.strip()
            self._set_pci_dev_info('func', MAX_FUNC, '%01x')
        if dbs:
            dbs_fields = dbs.split(':')
            if len(dbs_fields) > 3:
                raise exception.PciDeviceWrongAddressFormat(address=pci_addr)
            # If we got a partial address like ":00.", we need to turn this
            # into a domain of ANY, a bus of ANY, and a slot of 00. This code
            # allows the address bus and/or domain to be left off
            dbs_all = [ANY] * (3 - len(dbs_fields))
            dbs_all.extend(dbs_fields)
            dbs_checked = [s.strip() or ANY for s in dbs_all]
            self.domain, self.bus, self.slot = dbs_checked
            self._set_pci_dev_info('domain', MAX_DOMAIN, '%04x')
            self._set_pci_dev_info('bus', MAX_BUS, '%02x')
            self._set_pci_dev_info('slot', MAX_SLOT, '%02x')

    def match(self, phys_pci_addr: PciAddressSpec) -> bool:
        conditions = [
            self.domain in (ANY, phys_pci_addr.domain),
            self.bus in (ANY, phys_pci_addr.bus),
            self.slot in (ANY, phys_pci_addr.slot),
            self.func in (ANY, phys_pci_addr.func)
            ]
        return all(conditions)


class PciAddressRegexSpec(PciAddressSpec):
    """Manages the address fields with regex style.

    This function class will validate the address fields with regex style.
    The validation includes check for all PCI address attributes and validate
    their regex.
    """

    def __init__(self, pci_addr: dict) -> None:
        try:
            self.domain = pci_addr.get('domain', REGEX_ANY)
            self.bus = pci_addr.get('bus', REGEX_ANY)
            self.slot = pci_addr.get('slot', REGEX_ANY)
            self.func = pci_addr.get('function', REGEX_ANY)
            self.domain_regex = re.compile(self.domain)
            self.bus_regex = re.compile(self.bus)
            self.slot_regex = re.compile(self.slot)
            self.func_regex = re.compile(self.func)
        except re.error:
            raise exception.PciDeviceWrongAddressFormat(address=pci_addr)

    def match(self, phys_pci_addr: PciAddressSpec) -> bool:
        conditions = [
            bool(self.domain_regex.match(phys_pci_addr.domain)),
            bool(self.bus_regex.match(phys_pci_addr.bus)),
            bool(self.slot_regex.match(phys_pci_addr.slot)),
            bool(self.func_regex.match(phys_pci_addr.func))
            ]
        return all(conditions)


class WhitelistPciAddress(object):
    """Manages the address fields of the whitelist.

    This class checks the address fields of the pci.device_spec
    configuration option, validating the address fields.
    Example configs:

        | [pci]
        | device_spec = {"address":"*:0a:00.*",
        |                "physical_network":"physnet1"}
        | device_spec = {"address": {"domain": ".*",
                                     "bus": "02",
                                     "slot": "01",
                                     "function": "[0-2]"},
                         "physical_network":"net1"}
        | device_spec = {"vendor_id":"1137","product_id":"0071"}

    """

    def __init__(
        self, pci_addr: PCISpecAddressType, is_physical_function: bool
    ) -> None:
        self.is_physical_function = is_physical_function
        self._init_address_fields(pci_addr)

    def _check_physical_function(self) -> None:
        if self.pci_address_spec.is_single_address():
            self.is_physical_function = (
                utils.is_physical_function(
                    self.pci_address_spec.domain,
                    self.pci_address_spec.bus,
                    self.pci_address_spec.slot,
                    self.pci_address_spec.func))

    def _init_address_fields(self, pci_addr: PCISpecAddressType) -> None:
        self.pci_address_spec: PciAddressSpec
        if not self.is_physical_function:
            if isinstance(pci_addr, str):
                self.pci_address_spec = PciAddressGlobSpec(pci_addr)
            elif isinstance(pci_addr, dict):
                self.pci_address_spec = PciAddressRegexSpec(pci_addr)
            else:
                raise exception.PciDeviceWrongAddressFormat(address=pci_addr)
            self._check_physical_function()
        else:
            self.pci_address_spec = PhysicalPciAddress(pci_addr)

    def match(self, pci_addr: str, pci_phys_addr: ty.Optional[str]) -> bool:
        """Match a device to this PciAddress.

        Assume this is called with a ``pci_addr`` and ``pci_phys_addr``
        reported by libvirt. No attempt is made to verify if ``pci_addr`` is a
        VF of ``pci_phys_addr``.

        :param pci_addr: PCI address of the device to match.
        :param pci_phys_addr: PCI address of the parent of the device to match
                              (or None if the device is not a VF).
        """

        # Try to match on the parent PCI address if the PciDeviceSpec is a
        # PF (sriov is available) and the device to match is a VF.  This
        # makes it possible to specify the PCI address of a PF in the
        # pci.device_spec to match any of its VFs' PCI addresses.
        if self.is_physical_function and pci_phys_addr:
            pci_phys_addr_obj = PhysicalPciAddress(pci_phys_addr)
            if self.pci_address_spec.match(pci_phys_addr_obj):
                return True

        # Try to match on the device PCI address only.
        pci_addr_obj = PhysicalPciAddress(pci_addr)
        return self.pci_address_spec.match(pci_addr_obj)


class PciDeviceSpec(PciAddressSpec):
    def __init__(self, dev_spec: ty.Dict[str, str]) -> None:
        # stored for better error reporting
        self.dev_spec_conf = copy.deepcopy(dev_spec)
        # the non tag fields (i.e. address, devname) will be removed by
        # _init_dev_details
        self.tags = dev_spec
        self._init_dev_details()

    def _address_obj(self) -> ty.Optional[WhitelistPciAddress]:
        address_obj = None
        if self.dev_name:
            address_str, pf = utils.get_function_by_ifname(self.dev_name)
            if not address_str:
                return None
            # Note(moshele): In this case we always passing a string
            # of the PF pci address
            address_obj = WhitelistPciAddress(address_str, pf)
        else:  # use self.address
            address_obj = self.address

        return address_obj

    def _init_dev_details(self) -> None:
        self.vendor_id = self.tags.pop("vendor_id", ANY)
        self.product_id = self.tags.pop("product_id", ANY)
        self.dev_name = self.tags.pop("devname", None)
        self.address: ty.Optional[WhitelistPciAddress] = None
        # Note(moshele): The address attribute can be a string or a dict.
        # For glob syntax or specific pci it is a string and for regex syntax
        # it is a dict. The WhitelistPciAddress class handles both types.
        address = self.tags.pop("address", None)

        self.vendor_id = self.vendor_id.strip()
        self._set_pci_dev_info('vendor_id', MAX_VENDOR_ID, '%04x')
        self._set_pci_dev_info('product_id', MAX_PRODUCT_ID, '%04x')

        if address and self.dev_name:
            raise exception.PciDeviceInvalidDeviceName()

        if not self.dev_name:
            self.address = WhitelistPciAddress(address or '*:*:*.*', False)

        # PFs with remote_managed tags are explicitly not supported. If they
        # are tagged as such by mistake in the whitelist Nova will
        # raise an exception. The reason for excluding PFs is the lack of a way
        # for an instance to access the control plane at the remote side (e.g.
        # on a DPU) for managing the PF representor corresponding to the PF.
        address_obj = self._address_obj()
        self._remote_managed = strutils.bool_from_string(
            self.tags.get(PCI_REMOTE_MANAGED_TAG))
        if self._remote_managed:
            if address_obj is None:
                # Note that this will happen if a netdev was specified in the
                # whitelist but it is not actually present on a system - in
                # this case Nova is not able to look up an address by
                # a netdev name.
                raise exception.PciDeviceRemoteManagedNotPresent()
            elif address_obj.is_physical_function:
                pf_addr = str(address_obj.pci_address_spec)
                vf_product_id = utils.get_vf_product_id_by_pf_addr(pf_addr)
                # VF vendor IDs have to match the corresponding PF vendor IDs
                # per the SR-IOV spec so we use it for matching here.
                pf_vendor_id, pf_product_id = utils.get_pci_ids_by_pci_addr(
                    pf_addr)
                # Check the actual vendor ID and VF product ID of an assumed
                # VF (based on the actual PF). The VF product ID must match
                # the actual one if this is a VF device spec.
                if (self.product_id == vf_product_id and
                        self.vendor_id in (pf_vendor_id, ANY)):
                    pass
                elif (self.product_id in (pf_product_id, ANY) and
                      self.vendor_id in (pf_vendor_id, ANY)):
                    raise exception.PciDeviceInvalidPFRemoteManaged(
                        address_obj.pci_address_spec)
                else:
                    # The specified product and vendor IDs of what is supposed
                    # to be a VF corresponding to the PF PCI address do not
                    # match the actual ones for this PF. This means that the
                    # whitelist is invalid.
                    raise exception.PciConfigInvalidSpec(
                        reason=_('the specified VF vendor ID %(vendor_id)s and'
                                 ' product ID %(product_id)s do not match the'
                                 ' expected VF IDs based on the corresponding'
                                 ' PF identified by PCI address %(pf_addr)s') %
                        {'vendor_id': self.vendor_id,
                         'product_id': self.product_id,
                         'pf_addr': pf_addr})

    def _ensure_remote_managed_dev_vpd_serial(
        self, dev_dict: ty.Dict[str, ty.Any]) -> bool:
        """Ensure the presence of a serial number field in PCI VPD.

        A card serial number extracted from PCI VPD is required to allow a
        networking backend to identify which remote host needs to program a
        given device. So if a device is tagged as remote_managed, it must
        have the card serial number or be filtered out.
        """
        if not self._remote_managed:
            return True
        card_sn = dev_dict.get('capabilities', {}).get(
            'vpd', {}).get('card_serial_number')
        # None or empty card_serial_number should be filtered out. That would
        # mean either no serial number in the VPD (if present at all) or SN is
        # an empty string which is not useful for device identification.
        return bool(card_sn)

    def match(self, dev_dict: ty.Dict[str, ty.Any]) -> bool:
        address_obj: ty.Optional[WhitelistPciAddress] = self._address_obj()
        if not address_obj:
            return False

        return all([
            self.vendor_id in (ANY, dev_dict['vendor_id']),
            self.product_id in (ANY, dev_dict['product_id']),
            address_obj.match(dev_dict['address'],
                dev_dict.get('parent_addr')),
            self._ensure_remote_managed_dev_vpd_serial(dev_dict),
        ])

    def match_pci_obj(self, pci_obj: 'objects.PciDevice') -> bool:
        dev_dict = {
            'vendor_id': pci_obj.vendor_id,
            'product_id': pci_obj.product_id,
            'address': pci_obj.address,
            'parent_addr': pci_obj.parent_addr,
            'capabilities': {
                'vpd': {'card_serial_number': pci_obj.card_serial_number}}
        }
        return self.match(dev_dict)

    def get_tags(self) -> ty.Dict[str, str]:
        return self.tags
