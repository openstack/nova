# Copyright 2014 Red Hat, Inc.
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

"""Constants and helper APIs for dealing with virtualization types

The constants provide the standard names for all known guest
virtualization types. This is not to be confused with the Nova
hypervisor driver types, since one driver may support multiple
virtualization types and one virtualization type (eg 'xen') may
be supported by multiple drivers ('XenAPI' or  'Libvirt-Xen').
"""

from nova import exception


# This list is all known hypervisors
# even if not currently supported by OpenStack.
BAREMETAL = "baremetal"
BHYVE = "bhyve"
FAKE = "fake"
HYPERV = "hyperv"
KQEMU = "kqemu"
KVM = "kvm"
LXC = "lxc"
OPENVZ = "openvz"
PARALLELS = "parallels"
PHYP = "phyp"
QEMU = "qemu"
TEST = "test"
UML = "uml"
VBOX = "vbox"
VMWARE = "vmware"
XEN = "xen"
ZVM = "zvm"

ALL = (
    BAREMETAL,
    BHYVE,
    FAKE,
    HYPERV,
    KQEMU,
    KVM,
    LXC,
    OPENVZ,
    PARALLELS,
    PHYP,
    QEMU,
    TEST,
    UML,
    VBOX,
    VMWARE,
    XEN,
    ZVM,
)


def is_valid(name):
    """Check if a string is a valid hypervisor type

    :param name: hypervisor type name to validate

    :returns: True if @name is valid
    """
    return name in ALL


def canonicalize(name):
    """Canonicalize the hypervisor type name

    :param name: hypervisor type name to canonicalize

    :returns: a canonical hypervisor type name
    """

    if name is None:
        return None

    newname = name.lower()

    if newname == "xapi":
        newname = XEN
    elif newname == "powervm":
        # TODO(mriedem): Remove the translation shim in the 2015.2 'L' release.
        newname = PHYP

    if not is_valid(newname):
        raise exception.InvalidHypervisorVirtType(hv_type=name)

    return newname
