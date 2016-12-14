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
import re
import string

import six

from nova import exception
from nova.i18n import _
from nova.pci import utils

MAX_VENDOR_ID = 0xFFFF
MAX_PRODUCT_ID = 0xFFFF
MAX_FUNC = 0x7
MAX_DOMAIN = 0xFFFF
MAX_BUS = 0xFF
MAX_SLOT = 0x1F
ANY = '*'
REGEX_ANY = '.*'


def get_pci_dev_info(pci_obj, property, max, hex_value):
    a = getattr(pci_obj, property)
    if a == ANY:
        return
    try:
        v = int(a, 16)
    except ValueError:
        raise exception.PciConfigInvalidWhitelist(
            reason = "invalid %s %s" % (property, a))
    if v > max:
        raise exception.PciConfigInvalidWhitelist(
            reason=_("invalid %(property)s %(attr)s") %
                     {'property': property, 'attr': a})
    setattr(pci_obj, property, hex_value % v)


@six.add_metaclass(abc.ABCMeta)
class PciAddressSpec(object):
    """Abstract class for all PCI address spec styles

    This class checks the address fields of the pci.passthrough_whitelist
    """

    @abc.abstractmethod
    def match(self, pci_addr):
        pass

    def is_single_address(self):
        return all([
            all(c in string.hexdigits for c in self.domain),
            all(c in string.hexdigits for c in self.bus),
            all(c in string.hexdigits for c in self.slot),
            all(c in string.hexdigits for c in self.func)])


class PhysicalPciAddress(PciAddressSpec):
    """Manages the address fields for a fully-qualified PCI address.

    This function class will validate the address fields for a single
    PCI device.
    """
    def __init__(self, pci_addr):
        try:
            if isinstance(pci_addr, dict):
                self.domain = pci_addr['domain']
                self.bus = pci_addr['bus']
                self.slot = pci_addr['slot']
                self.func = pci_addr['function']
            else:
                self.domain, self.bus, self.slot, self.func = (
                    utils.get_pci_address_fields(pci_addr))
            get_pci_dev_info(self, 'func', MAX_FUNC, '%1x')
            get_pci_dev_info(self, 'domain', MAX_DOMAIN, '%04x')
            get_pci_dev_info(self, 'bus', MAX_BUS, '%02x')
            get_pci_dev_info(self, 'slot', MAX_SLOT, '%02x')
        except (KeyError, ValueError):
            raise exception.PciDeviceWrongAddressFormat(address=pci_addr)

    def match(self, phys_pci_addr):
        conditions = [
            self.domain == phys_pci_addr.domain,
            self.bus == phys_pci_addr.bus,
            self.slot == phys_pci_addr.slot,
            self.func == phys_pci_addr.func,
            ]
        return all(conditions)


class PciAddressGlobSpec(PciAddressSpec):
    """Manages the address fields with glob style.

    This function class will validate the address fields with glob style,
    check for wildcards, and insert wildcards where the field is left blank.
    """

    def __init__(self, pci_addr):
        self.domain = ANY
        self.bus = ANY
        self.slot = ANY
        self.func = ANY

        dbs, sep, func = pci_addr.partition('.')
        if func:
            self.func = func.strip()
            get_pci_dev_info(self, 'func', MAX_FUNC, '%01x')
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
            get_pci_dev_info(self, 'domain', MAX_DOMAIN, '%04x')
            get_pci_dev_info(self, 'bus', MAX_BUS, '%02x')
            get_pci_dev_info(self, 'slot', MAX_SLOT, '%02x')

    def match(self, phys_pci_addr):
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
    def __init__(self, pci_addr):
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

    def match(self, phys_pci_addr):
        conditions = [
            bool(self.domain_regex.match(phys_pci_addr.domain)),
            bool(self.bus_regex.match(phys_pci_addr.bus)),
            bool(self.slot_regex.match(phys_pci_addr.slot)),
            bool(self.func_regex.match(phys_pci_addr.func))
            ]
        return all(conditions)


class WhitelistPciAddress(object):
    """Manages the address fields of the whitelist.

    This class checks the address fields of the pci.passthrough_whitelist
    configuration option, validating the address fields.
    Example config are:

        | [pci]
        | passthrough_whitelist = {"address":"*:0a:00.*",
        |                          "physical_network":"physnet1"}
        | passthrough_whitelist = {"address": {"domain": ".*",
                                               "bus": "02",
                                               "slot": "01",
                                               "function": "[0-2]"},
                                    "physical_network":"net1"}
        | passthrough_whitelist = {"vendor_id":"1137","product_id":"0071"}

    """
    def __init__(self, pci_addr, is_physical_function):
        self.is_physical_function = is_physical_function
        self._init_address_fields(pci_addr)

    def _check_physical_function(self):
        if self.pci_address_spec.is_single_address():
            self.is_physical_function = (
                utils.is_physical_function(
                    self.pci_address_spec.domain,
                    self.pci_address_spec.bus,
                    self.pci_address_spec.slot,
                    self.pci_address_spec.func))

    def _init_address_fields(self, pci_addr):
        if not self.is_physical_function:
            if isinstance(pci_addr, six.string_types):
                self.pci_address_spec = PciAddressGlobSpec(pci_addr)
            elif isinstance(pci_addr, dict):
                self.pci_address_spec = PciAddressRegexSpec(pci_addr)
            else:
                raise exception.PciDeviceWrongAddressFormat(address=pci_addr)
            self._check_physical_function()
        else:
            self.pci_address_spec = PhysicalPciAddress(pci_addr)

    def match(self, pci_addr, pci_phys_addr):
        """Match a device to this PciAddress.  Assume this is called given
        pci_addr and pci_phys_addr reported by libvirt, no attempt is made to
        verify if pci_addr is a VF of pci_phys_addr.

        :param pci_addr: PCI address of the device to match.
        :param pci_phys_addr: PCI address of the parent of the device to match
                              (or None if the device is not a VF).
        """

        # Try to match on the parent PCI address if the PciDeviceSpec is a
        # PF (sriov is available) and the device to match is a VF.  This
        # makes possible to specify the PCI address of a PF in the
        # pci_passthrough_whitelist to match any of it's VFs PCI devices.
        if self.is_physical_function and pci_phys_addr:
            pci_phys_addr_obj = PhysicalPciAddress(pci_phys_addr)
            if self.pci_address_spec.match(pci_phys_addr_obj):
                return True

        # Try to match on the device PCI address only.
        pci_addr_obj = PhysicalPciAddress(pci_addr)
        return self.pci_address_spec.match(pci_addr_obj)


class PciDeviceSpec(object):
    def __init__(self, dev_spec):
        self.tags = dev_spec
        self._init_dev_details()

    def _init_dev_details(self):
        self.vendor_id = self.tags.pop("vendor_id", ANY)
        self.product_id = self.tags.pop("product_id", ANY)
        # Note(moshele): The address attribute can be a string or a dict.
        # For glob syntax or specific pci it is a string and for regex syntax
        # it is a dict. The WhitelistPciAddress class handles both types.
        self.address = self.tags.pop("address", None)
        self.dev_name = self.tags.pop("devname", None)

        self.vendor_id = self.vendor_id.strip()
        get_pci_dev_info(self, 'vendor_id', MAX_VENDOR_ID, '%04x')
        get_pci_dev_info(self, 'product_id', MAX_PRODUCT_ID, '%04x')

        if self.address and self.dev_name:
            raise exception.PciDeviceInvalidDeviceName()
        if not self.dev_name:
            pci_address = self.address or "*:*:*.*"
            self.address = WhitelistPciAddress(pci_address, False)

    def match(self, dev_dict):
        if self.dev_name:
            address_str, pf = utils.get_function_by_ifname(
                self.dev_name)
            if not address_str:
                return False
            # Note(moshele): In this case we always passing a string
            # of the PF pci address
            address_obj = WhitelistPciAddress(address_str, pf)
        elif self.address:
            address_obj = self.address
        return all([
            self.vendor_id in (ANY, dev_dict['vendor_id']),
            self.product_id in (ANY, dev_dict['product_id']),
            address_obj.match(dev_dict['address'],
                dev_dict.get('parent_addr'))])

    def match_pci_obj(self, pci_obj):
        return self.match({'vendor_id': pci_obj.vendor_id,
                            'product_id': pci_obj.product_id,
                            'address': pci_obj.address,
                            'parent_addr': pci_obj.parent_addr})

    def get_tags(self):
        return self.tags
