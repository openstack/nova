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

from nova import exception
from nova.i18n import _LE
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

PCI_VENDOR_PATTERN = "^(hex{4})$".replace("hex", "[\da-fA-F]")
_PCI_ADDRESS_PATTERN = ("^(hex{4}):(hex{2}):(hex{2}).(oct{1})$".
                                             replace("hex", "[\da-fA-F]").
                                             replace("oct", "[0-7]"))
_PCI_ADDRESS_REGEX = re.compile(_PCI_ADDRESS_PATTERN)

_VIRTFN_RE = re.compile("virtfn\d+")


def pci_device_prop_match(pci_dev, specs):
    """Check if the pci_dev meet spec requirement

    Specs is a list of PCI device property requirements.
    An example of device requirement that the PCI should be either:
    a) Device with vendor_id as 0x8086 and product_id as 0x8259, or
    b) Device with vendor_id as 0x10de and product_id as 0x10d8:

    [{"vendor_id":"8086", "product_id":"8259"},
     {"vendor_id":"10de", "product_id":"10d8"}]

    """
    def _matching_devices(spec):
        return all(pci_dev.get(k) == v for k, v in spec.iteritems())

    return any(_matching_devices(spec) for spec in specs)


def parse_address(address):
    """Returns (domain, bus, slot, function) from PCI address that is stored in
    PciDevice DB table.
    """
    m = _PCI_ADDRESS_REGEX.match(address)
    if not m:
        raise exception.PciDeviceWrongAddressFormat(address=address)
    return m.groups()


def get_pci_address_fields(pci_addr):
    dbs, sep, func = pci_addr.partition('.')
    domain, bus, slot = dbs.split(':')
    return (domain, bus, slot, func)


def get_function_by_ifname(ifname):
    """Given the device name, returns the PCI address of a an device
    and returns True if the address in a physical function.
    """
    try:
        dev_path = "/sys/class/net/%s/device" % ifname
        dev_info = os.listdir(dev_path)
        for dev_file in dev_info:
            if _VIRTFN_RE.match(dev_file):
                return os.readlink(dev_path).strip("./"), True
        else:
            return os.readlink(dev_path).strip("./"), False
    except Exception:
        LOG.error(_LE("PCI device %s not found") % ifname)
        return None, False


def is_physical_function(pci_addr):
    dev_path = "/sys/bus/pci/devices/%(d)s:%(b)s:%(s)s.%(f)s/" % {
        "d": pci_addr.domain, "b": pci_addr.bus,
        "s": pci_addr.slot, "f": pci_addr.func}
    try:
        dev_info = os.listdir(dev_path)
        for dev_file in dev_info:
            if _VIRTFN_RE.match(dev_file):
                return True
        else:
            return False
    except Exception:
        LOG.error(_LE("PCI device %s not found") % dev_path)
        return False


def get_ifname_by_pci_address(pci_addr, pf_interface=False):
    """Get the interface name based on a VF's pci address

    The returned interface name is either the parent PF's or that of the VF
    itself based on the argument of pf_interface.
    """
    if pf_interface:
        dev_path = "/sys/bus/pci/devices/%s/physfn/net" % (pci_addr)
    else:
        dev_path = "/sys/bus/pci/devices/%s/net" % (pci_addr)
    try:
        dev_info = os.listdir(dev_path)
        return dev_info.pop()
    except Exception:
        raise exception.PciDeviceNotFoundById(id=pci_addr)


def get_vf_num_by_pci_address(pci_addr):
    """Get the VF number based on a VF's pci address

    A VF is associated with an VF number, which ip link command uses to
    configure it. This number can be obtained from the PCI device filesystem.
    """
    VIRTFN_RE = re.compile("virtfn(\d+)")
    virtfns_path = "/sys/bus/pci/devices/%s/physfn/virtfn*" % (pci_addr)
    vf_num = None
    try:
        for vf_path in glob.iglob(virtfns_path):
            if re.search(pci_addr, os.readlink(vf_path)):
                t = VIRTFN_RE.search(vf_path)
                vf_num = t.group(1)
                break
    except Exception:
        pass
    if vf_num is None:
        raise exception.PciDeviceNotFoundById(id=pci_addr)
    return vf_num
