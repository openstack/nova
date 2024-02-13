====
UEFI
====

.. versionadded:: 17.0.0 (Queens)

Nova supports configuring a `UEFI bootloader`__ for guests. This brings about
important advantages over legacy BIOS bootloaders and allows for features such
as :doc:`secure-boot`.

.. __: https://en.wikipedia.org/wiki/Unified_Extensible_Firmware_Interface


Enabling UEFI
-------------

Currently the configuration of UEFI guest bootloaders is only supported when
using the libvirt compute driver with a :oslo.config:option:`libvirt.virt_type`
of ``kvm`` or ``qemu``. When using the libvirt compute driver with AArch64-based guests,
UEFI is automatically enabled as AArch64 does not support BIOS.

.. todo::

    Update this once compute drivers start reporting a trait indicating UEFI
    bootloader support.


Configuring a flavor or image
-----------------------------

Configuring a UEFI bootloader varies depending on the compute driver in use.

.. rubric:: Libvirt

UEFI support is enabled by default on AArch64-based guests. For other guest
architectures, you can request UEFI support with libvirt by setting the
``hw_firmware_type`` image property to ``uefi``. For example:

.. code-block:: bash

    $ openstack image set --property hw_firmware_type=uefi $IMAGE

References
----------

* `Open Virtual Machine Firmware (OVMF) Status Report`__
* `Anatomy of a boot, a QEMU perspective`__

.. __: http://www.linux-kvm.org/downloads/lersek/ovmf-whitepaper-c770f8c.txt
.. __: https://www.qemu.org/2020/07/03/anatomy-of-a-boot/
