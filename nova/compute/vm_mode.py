# Copyright 2012 Red Hat, Inc.
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

"""Possible vm modes for instances.

Compute instance vm modes represent the host/guest ABI used for the
virtual machine / container. Individual hypervisors may support
multiple different vm modes per host. Available vm modes for a hypervisor
driver may also vary according to the architecture it is running on.

The 'vm_mode' parameter can be set against an instance to
choose what sort of VM to boot.

"""

from nova import exception

HVM = "hvm"  # Native ABI (aka fully virtualized)
XEN = "xen"  # Xen 3.0 paravirtualized
UML = "uml"  # User Mode Linux paravirtualized
EXE = "exe"  # Executables in containers

ALL = [HVM, XEN, UML, EXE]


def get_from_instance(instance):
    """Get the vm mode for an instance

    :param name: instance object to query

    :returns: canonicalized vm mode for the instance
    """

    mode = instance['vm_mode']
    return canonicalize(mode)


def is_valid(name):
    """Check if a string is a valid vm mode

    :param name: vm mode name to validate

    :returns: True if @name is valid
    """

    return name in ALL


def canonicalize(mode):
    """Canonicalize the vm mode

    :param name: vm mode name to canonicalize

    :returns: a canonical vm mode name
    """

    if mode is None:
        return None

    mode = mode.lower()

    # For compatibility with pre-Folsom deployments
    if mode == "pv":
        mode = XEN

    if mode == "hv":
        mode = HVM

    if mode == "baremetal":
        mode = HVM

    if not is_valid(mode):
        raise exception.InvalidVirtualMachineMode(vmmode=mode)

    return mode
