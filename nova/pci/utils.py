# Copyright (c) 2013 Intel, Inc.
# Copyright (c) 2012 OpenStack Foundation
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

import glob
import os
import re
import typing as ty

from oslo_log import log as logging

from nova import exception

if ty.TYPE_CHECKING:
    # avoid circular import
    from nova.pci import stats

LOG = logging.getLogger(__name__)

PCI_VENDOR_PATTERN = "^(hex{4})$".replace("hex", r"[\da-fA-F]")
_PCI_ADDRESS_PATTERN = ("^(hex{4}):(hex{2}):(hex{2}).(oct{1})$".
                                             replace("hex", r"[\da-fA-F]").
                                             replace("oct", "[0-7]"))
_PCI_ADDRESS_REGEX = re.compile(_PCI_ADDRESS_PATTERN)
_SRIOV_TOTALVFS = "sriov_totalvfs"


def pci_device_prop_match(
    pci_dev: 'stats.Pool', specs: ty.List[ty.Dict[str, str]],
) -> bool:
    """Check if the pci_dev meet spec requirement

    Specs is a list of PCI device property requirements.
    An example of device requirement that the PCI should be either:
    a) Device with vendor_id as 0x8086 and product_id as 0x8259, or
    b) Device with vendor_id as 0x10de and product_id as 0x10d8:

    [{"vendor_id":"8086", "product_id":"8259"},
     {"vendor_id":"10de", "product_id":"10d8",
      "capabilities_network": ["rx", "tx", "tso", "gso"]}]

    """

    def _matching_devices(spec: ty.Dict[str, str]) -> bool:
        for k, v in spec.items():
            pci_dev_v = pci_dev.get(k)
            if isinstance(v, list) and isinstance(pci_dev_v, list):
                if not all(x in pci_dev.get(k) for x in v):
                    return False
            else:
                # We don't need to check case for tags in order to avoid any
                # mismatch with the tags provided by users for port
                # binding profile and the ones configured by operators
                # with pci whitelist option.
                if isinstance(v, str):
                    v = v.lower()
                if isinstance(pci_dev_v, str):
                    pci_dev_v = pci_dev_v.lower()
                if pci_dev_v != v:
                    return False
        return True

    return any(_matching_devices(spec) for spec in specs)


def parse_address(address: str) -> ty.Sequence[str]:
    """Parse a PCI address.

    Returns (domain, bus, slot, function) from PCI address that is stored in
    PciDevice DB table.
    """
    m = _PCI_ADDRESS_REGEX.match(address)
    if not m:
        raise exception.PciDeviceWrongAddressFormat(address=address)
    return m.groups()


def get_pci_address_fields(pci_addr: str) -> ty.Tuple[str, str, str, str]:
    """Parse a fully-specified PCI device address.

    Does not validate that the components are valid hex or wildcard values.

    :param pci_addr: A string of the form "<domain>:<bus>:<slot>.<function>".
    :return: A 4-tuple of strings ("<domain>", "<bus>", "<slot>", "<function>")
    """
    dbs, sep, func = pci_addr.partition('.')
    domain, bus, slot = dbs.split(':')
    return domain, bus, slot, func


def get_pci_address(domain: str, bus: str, slot: str, func: str) -> str:
    """Assembles PCI address components into a fully-specified PCI address.

    Does not validate that the components are valid hex or wildcard values.

    :param domain, bus, slot, func: Hex or wildcard strings.
    :return: A string of the form "<domain>:<bus>:<slot>.<function>".
    """
    return '%s:%s:%s.%s' % (domain, bus, slot, func)


def get_function_by_ifname(ifname: str) -> ty.Tuple[ty.Optional[str], bool]:
    """Given the device name, returns the PCI address of a device
    and returns True if the address is in a physical function.
    """
    dev_path = "/sys/class/net/%s/device" % ifname
    sriov_totalvfs = 0
    if os.path.isdir(dev_path):
        try:
            # sriov_totalvfs contains the maximum possible VFs for this PF
            with open(os.path.join(dev_path, _SRIOV_TOTALVFS)) as fd:
                sriov_totalvfs = int(fd.read())
                return (os.readlink(dev_path).strip("./"),
                        sriov_totalvfs > 0)
        except (IOError, ValueError):
            return os.readlink(dev_path).strip("./"), False
    return None, False


def is_physical_function(
    domain: str, bus: str, slot: str, function: str,
) -> bool:
    dev_path = "/sys/bus/pci/devices/%(d)s:%(b)s:%(s)s.%(f)s/" % {
        "d": domain, "b": bus, "s": slot, "f": function}
    if os.path.isdir(dev_path):
        try:
            with open(dev_path + _SRIOV_TOTALVFS) as fd:
                sriov_totalvfs = int(fd.read())
                return sriov_totalvfs > 0
        except (IOError, ValueError):
            pass
    return False


def _get_sysfs_netdev_path(pci_addr: str, pf_interface: bool) -> str:
    """Get the sysfs path based on the PCI address of the device.

    Assumes a networking device - will not check for the existence of the path.
    """
    if pf_interface:
        return "/sys/bus/pci/devices/%s/physfn/net" % pci_addr
    return "/sys/bus/pci/devices/%s/net" % pci_addr


def get_ifname_by_pci_address(
    pci_addr: str, pf_interface: bool = False,
) -> str:
    """Get the interface name based on a VF's pci address.

    The returned interface name is either the parent PF's or that of the VF
    itself based on the argument of pf_interface.
    """
    dev_path = _get_sysfs_netdev_path(pci_addr, pf_interface)
    try:
        dev_info = os.listdir(dev_path)
        return dev_info.pop()
    except Exception:
        raise exception.PciDeviceNotFoundById(id=pci_addr)


def get_mac_by_pci_address(pci_addr: str, pf_interface: bool = False) -> str:
    """Get the MAC address of the nic based on its PCI address.

    Raises PciDeviceNotFoundById in case the pci device is not a NIC
    """
    dev_path = _get_sysfs_netdev_path(pci_addr, pf_interface)
    if_name = get_ifname_by_pci_address(pci_addr, pf_interface)
    addr_file = os.path.join(dev_path, if_name, 'address')

    try:
        with open(addr_file) as f:
            mac = next(f).strip()
            return mac
    except (IOError, StopIteration) as e:
        LOG.warning("Could not find the expected sysfs file for "
                    "determining the MAC address of the PCI device "
                    "%(addr)s. May not be a NIC. Error: %(e)s",
                    {'addr': pci_addr, 'e': e})
        raise exception.PciDeviceNotFoundById(id=pci_addr)


def get_vf_num_by_pci_address(pci_addr: str) -> int:
    """Get the VF number based on a VF's pci address

    A VF is associated with an VF number, which ip link command uses to
    configure it. This number can be obtained from the PCI device filesystem.
    """
    VIRTFN_RE = re.compile(r"virtfn(\d+)")
    virtfns_path = "/sys/bus/pci/devices/%s/physfn/virtfn*" % (pci_addr)
    vf_num = None

    for vf_path in glob.iglob(virtfns_path):
        if re.search(pci_addr, os.readlink(vf_path)):
            t = VIRTFN_RE.search(vf_path)
            if t:
                vf_num = t.group(1)
                break
    else:
        raise exception.PciDeviceNotFoundById(id=pci_addr)

    return int(vf_num)


def get_vf_product_id_by_pf_addr(pci_addr: str) -> str:
    """Get the VF product ID for a given PF.

    "Product ID" or Device ID in the PCIe spec terms for a PF is
    possible to retrieve via the VF Device ID field present as of
    SR-IOV 1.0 in the "3.3.11. VF Device ID (1Ah)" section. It is
    described as a field that "contains the Device ID that should
    be presented for every VF to the SI".

    It is available as of Linux kernel 4.15, commit
    7dfca15276fc3f18411a2b2182704fa1222bcb60

    :param pci_addr: A string of the form "<domain>:<bus>:<slot>.<function>".
    :return: A string containing a product ID of a VF corresponding to the PF.
    """
    sriov_vf_device_path = f"/sys/bus/pci/devices/{pci_addr}/sriov_vf_device"
    try:
        with open(sriov_vf_device_path) as f:
            vf_product_id = f.readline().strip()
    except IOError as e:
        LOG.warning(
            "Could not find the expected sysfs file for "
            "determining the VF product ID of a PCI VF by PF"
            "with addr %(addr)s. May not be a PF. Error: %(e)s",
            {"addr": pci_addr, "e": e},
        )
        raise exception.PciDeviceNotFoundById(id=pci_addr)
    if not vf_product_id:
        raise ValueError("sriov_vf_device file does not contain"
                         " a VF product ID")
    return vf_product_id


def get_pci_ids_by_pci_addr(pci_addr: str) -> ty.Tuple[str, ...]:
    """Get the product ID and vendor ID for a given PCI device.

    :param pci_addr: A string of the form "<domain>:<bus>:<slot>.<function>".
    :return: A list containing a vendor and product ids.
    """
    id_prefix = f"/sys/bus/pci/devices/{pci_addr}"
    ids: ty.List[str] = []
    for id_name in ("vendor", "product"):
        try:
            with open(os.path.join(id_prefix, id_name)) as f:
                id_value = f.readline()
                if not id_value:
                    raise ValueError(f"{id_name} file does not contain"
                                     " a valid value")
                ids.append(id_value.strip().replace("0x", ""))
        except IOError as e:
            LOG.warning(
                "Could not find the expected sysfs file for "
                f"determining the {id_name} ID of a PCI device "
                "with addr %(addr)s. Error: %(e)s",
                {"addr": pci_addr, "e": e},
            )
            raise exception.PciDeviceNotFoundById(id=pci_addr)
    return tuple(ids)
