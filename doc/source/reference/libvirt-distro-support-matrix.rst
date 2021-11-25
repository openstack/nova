Libvirt virt driver OS distribution support matrix
==================================================

This page documents the libvirt versions present in the various distro versions
that OpenStack Nova aims to be deployable with.

.. note::

    This document was previously hosted on the OpenStack wiki:

    https://wiki.openstack.org/wiki/LibvirtDistroSupportMatrix

Libvirt minimum version change policy
-------------------------------------

At the start of each Nova development cycle this matrix will be consulted to
determine if it is viable to drop support for any end-of-life or otherwise
undesired distro versions. Based on this distro evaluation, it may be possible
to increase the minimum required version of libvirt in Nova, and thus drop some
compatibility code for older versions.

When a decision to update the minimum required libvirt version is made, there
must be a warning issued for one cycle. This is achieved by editing
``nova/virt/libvirt/driver.py`` to set ``NEXT_MIN_LIBVIRT_VERSION``.
For example:

.. code::

    NEXT_MIN_LIBVIRT_VERSION = (X, Y, Z)

This causes a deprecation warning to be emitted when Nova starts up warning the
admin that the version of libvirt in use on the host will no longer be
supported in the subsequent release.

After a version has been listed in ``NEXT_MIN_LIBVIRT_VERSION`` for one release
cycle, the corresponding actual minimum required libvirt can be updated by
setting

.. code::

    MIN_LIBVIRT_VERSION = (X, Y, Z)

At this point of course, an even newer version might be set in
``NEXT_MIN_LIBVIRT_VERSION`` to repeat the process....

An email should also be sent at this point to the
``openstack-discuss@lists.openstack.org`` mailing list as a courtesy raising
awareness of the change in minimum version requirements in the upcoming
release, for example:

http://lists.openstack.org/pipermail/openstack-discuss/2021-January/019849.html

There is more background on the rationale used for picking minimum versions in
the operators mailing list thread here:

http://lists.openstack.org/pipermail/openstack-operators/2015-May/007012.html

QEMU minimum version change policy
----------------------------------

After choosing a minimum libvirt version, the minimum QEMU version is
determined by looking for the lowest QEMU version from all the distros that
support the decided libvirt version.

``MIN_{LIBVIRT,QEMU}_VERSION`` and ``NEXT_MIN_{LIBVIRT,QEMU}_VERSION`` table
----------------------------------------------------------------------------

.. list-table:: OpenStack Nova libvirt/QEMU Support Matrix

    * - OpenStack Release
      - Nova Release
      - ``MIN_LIBVIRT_VERSION``
      - ``NEXT_MIN_LIBVIRT_VERSION``
      - ``MIN_QEMU_VERSION``
      - ``NEXT_MIN_QEMU_VERSION``
    * - Havana
      - 2013.2.0
      - 0.9.6
      - 0.9.6
      -
      -
    * - Icehouse
      - 2014.1
      - 0.9.6
      - 0.9.11
      -
      -
    * - Juno
      - 2014.2.0
      - 0.9.11
      - 0.9.11
      -
      -
    * - Kilo
      - 2015.1.0
      - 0.9.11
      - 0.9.11
      -
      -
    * - Liberty
      - 12.0.0
      - 0.9.11
      - 0.10.2
      -
      -
    * - Mitaka
      - 13.0.0
      - 0.10.2
      - 1.2.1
      -
      -
    * - Newton
      - 14.0.0
      - 1.2.1
      - 1.2.1
      - 1.5.3
      - 1.5.3
    * - Ocata
      - 15.0.0
      - 1.2.1
      - 1.2.9
      - 1.5.3
      - 2.1.0
    * - Pike
      - 16.0.0
      - 1.2.9
      - 1.3.1
      - 2.1.0
      - 2.5.0
    * - Queens
      - 17.0.0
      - 1.2.9
      - 1.3.1
      - 2.1.0
      - 2.5.0
    * - Rocky
      - 18.0.0
      - 1.3.1
      - 3.0.0
      - 2.5.0
      - 2.8.0
    * - Stein
      - 19.0.0
      - 3.0.0
      - 4.0.0
      - 2.8.0
      - 2.11.0
    * - Train
      - 20.0.0
      - 3.0.0
      - 4.0.0
      - 2.8.0
      - 2.11.0
    * - Ussuri
      - 21.0.0
      - 4.0.0
      - 5.0.0
      - 2.11.0
      - 4.0.0
    * - Victoria
      - 22.0.0
      - 5.0.0
      - 6.0.0
      - 4.0.0
      - 4.2.0
    * - Wallaby
      - 23.0.0
      - 6.0.0
      - 7.0.0
      - 4.2.0
      - 5.2.0
    * - Xena
      - 24.0.0
      - 6.0.0
      - 7.0.0
      - 4.2.0
      - 5.2.0

OS distribution versions
------------------------

This table provides information on a representative sample of OS distros and
the version of libirt/QEMU/libguestfs that they ship. This is **NOT** intended
to be an exhaustive list of distros where OpenStack Nova can run - it is
intended to run on any Linux distro that can satisfy the minimum required
software versions. This table merely aims to help identify when minimum
required versions can be reasonably updated without losing support for
important OS distros.

.. list-table:: Distro libvirt/QEMU Support Table

    * - OS Distro
      - GA date
      - Libvirt
      - QEMU/KVM
      - libguestfs
    * - **CentOS Stream**
      -
      -
      -
      -
    * - 8
      - Provided by the advanced-virtualization module as of 2021-11-18.
      - 7.0.0-14
      - 5.2.0-16
      - 1.44.0-2
    * - 9
      - As of 2021-11-18.
      - 7.8.0-1
      - 6.1.0-6
      - 1.46.0-4
    * - **Debian**
      -
      -
      -
      -
    * - 11.x (Bullseye) ("stable")
      - 2021-10-09
      - 7.0.0
      - 5.2
      - 1.42.0
    * - 12.x (Bookworm) ("testing")
      - No GA date as of 2021-11-18
      - 7.6.0
      - 6.1
      - 1.42.0
    * - **Fedora**
      -
      -
      -
      -
    * - 34
      - 2021-04-27
      - 7.0.0
      - 5.2.0
      - 1.45.4
    * - 35
      - 2021-11-02
      - 7.6.0
      - 6.1.0
      - 1.46.0
    * - **SUSE**
      -
      -
      -
      -
    * - Leap 15.2
      - 2020-07-02
      - 6.0.0
      - 4.2.0
      - 1.38.0
    * - Leap 15.3
      - 2021-06-02
      - 7.2.0
      - 6.0.0
      - 1.44.1
    * - **RHEL**
      -
      -
      -
      -
    * - 8.2
      - 2020-04-28
      - 6.0.0-17.2
      - 4.2.0-19
      - 1.40.2-22
    * - 8.3
      - 2020-10-29
      - 6.0.0-25.5
      - 4.2.0-29
      - 1.40.2-24
    * - 8.4
      - 2021-05-18
      - 7.0.0-8
      - 5.2.0-10
      - 1.44.0-2
    * - 8.5
      - 2021-11-09
      - 7.6.0-6
      - 6.0.0-33
      - 1.44.0-3
    * - **SLES**
      -
      -
      -
      -
    * - 15 (SP2)
      - 2020
      - 6.0.0
      - 4.2.1
      - 1.38.0
    * - 15 (SP3)
      - 2021
      - 7.1.0
      - 5.2.0
      - 1.38.0
    * - **Ubuntu**
      -
      -
      -
      -
    * - 20.04 (Focal Fossa LTS)
      - 2020-04-23
      - 6.0.0
      - 4.2
      - 1.40.2
    * - 21.04 (Hirsute Hippo)
      - 2021-04-22
      - 7.0.0
      - 5.2
      - 1.44.1

.. NB: maintain alphabetical ordering of distros, followed by oldest released
       versions first
