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

"""Constants and helper APIs for dealing with CPU architectures

The constants provide the standard names for all known processor
architectures. Many have multiple variants to deal with big-endian
vs little-endian modes, as well as 32 vs 64 bit word sizes. These
names are chosen to be identical to the architecture names expected
by libvirt, so if ever adding new ones, ensure it matches libvirt's
expectation.
"""

import os

from nova import exception

ALPHA = "alpha"
ARMV6 = "armv6"
ARMV7 = "armv7l"
ARMV7B = "armv7b"

AARCH64 = "aarch64"
CRIS = "cris"
I686 = "i686"
IA64 = "ia64"
LM32 = "lm32"

M68K = "m68k"
MICROBLAZE = "microblaze"
MICROBLAZEEL = "microblazeel"
MIPS = "mips"
MIPSEL = "mipsel"

MIPS64 = "mips64"
MIPS64EL = "mips64el"
OPENRISC = "openrisc"
PARISC = "parisc"
PARISC64 = "parisc64"

PPC = "ppc"
PPCLE = "ppcle"
PPC64 = "ppc64"
PPC64LE = "ppc64le"
PPCEMB = "ppcemb"

S390 = "s390"
S390X = "s390x"
SH4 = "sh4"
SH4EB = "sh4eb"
SPARC = "sparc"

SPARC64 = "sparc64"
UNICORE32 = "unicore32"
X86_64 = "x86_64"
XTENSA = "xtensa"
XTENSAEB = "xtensaeb"


ALL = [
    ALPHA,
    ARMV6,
    ARMV7,
    ARMV7B,

    AARCH64,
    CRIS,
    I686,
    IA64,
    LM32,

    M68K,
    MICROBLAZE,
    MICROBLAZEEL,
    MIPS,
    MIPSEL,

    MIPS64,
    MIPS64EL,
    OPENRISC,
    PARISC,
    PARISC64,

    PPC,
    PPCLE,
    PPC64,
    PPC64LE,
    PPCEMB,

    S390,
    S390X,
    SH4,
    SH4EB,
    SPARC,

    SPARC64,
    UNICORE32,
    X86_64,
    XTENSA,
    XTENSAEB,
]


def from_host():
    """Get the architecture of the host OS

    :returns: the canonicalized host architecture
    """

    return canonicalize(os.uname()[4])


def is_valid(name):
    """Check if a string is a valid architecture

    :param name: architecture name to validate

    :returns: True if @name is valid
    """

    return name in ALL


def canonicalize(name):
    """Canonicalize the architecture name

    :param name: architecture name to canonicalize

    :returns: a canonical architecture name
    """

    if name is None:
        return None

    newname = name.lower()

    if newname in ("i386", "i486", "i586"):
        newname = I686

    # Xen mistake from Icehouse or earlier
    if newname in ("x86_32", "x86_32p"):
        newname = I686

    if newname == "amd64":
        newname = X86_64

    if not is_valid(newname):
        raise exception.InvalidArchitectureName(arch=name)

    return newname
