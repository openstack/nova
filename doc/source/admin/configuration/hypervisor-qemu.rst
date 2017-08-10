.. _compute_qemu:

====
QEMU
====

From the perspective of the Compute service, the QEMU hypervisor is
very similar to the KVM hypervisor. Both are controlled through libvirt,
both support the same feature set, and all virtual machine images that
are compatible with KVM are also compatible with QEMU.
The main difference is that QEMU does not support native virtualization.
Consequently, QEMU has worse performance than KVM and is a poor choice
for a production deployment.

The typical uses cases for QEMU are

* Running on older hardware that lacks virtualization support.
* Running the Compute service inside of a virtual machine for
  development or testing purposes, where the hypervisor does not
  support native virtualization for guests.

To enable QEMU, add these settings to ``nova.conf``:

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = qemu

For some operations you may also have to install the
:command:`guestmount` utility:

On Ubuntu:

.. code-block:: console

   # apt-get install guestmount

On Red Hat Enterprise Linux, Fedora, or CentOS:

.. code-block:: console

   # yum install libguestfs-tools

On openSUSE:

.. code-block:: console

   # zypper install guestfs-tools

The QEMU hypervisor supports the following virtual machine image formats:

* Raw
* QEMU Copy-on-write (qcow2)
* VMware virtual machine disk format (vmdk)
