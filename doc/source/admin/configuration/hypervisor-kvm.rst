===
KVM
===

KVM is configured as the default hypervisor for Compute.

.. note::

   This document contains several sections about hypervisor selection.  If you
   are reading this document linearly, you do not want to load the KVM module
   before you install ``nova-compute``.  The ``nova-compute`` service depends
   on qemu-kvm, which installs ``/lib/udev/rules.d/45-qemu-kvm.rules``, which
   sets the correct permissions on the ``/dev/kvm`` device node.

The KVM hypervisor supports the following virtual machine image formats:

* Raw
* QEMU Copy-on-write (QCOW2)
* QED Qemu Enhanced Disk
* VMware virtual machine disk format (vmdk)

This section describes how to enable KVM on your system.  For more information,
see the following distribution-specific documentation:

* `Fedora: Virtualization Getting Started Guide`__
* `Ubuntu: KVM/Installation`__
* `Debian: KVM Guide`__
* `Red Hat Enterprise Linux (RHEL): Getting started with virtualization`__
* `openSUSE: Setting Up a KVM VM Host Server`__
* `SLES: Virtualization with KVM`__.

.. __: https://docs.fedoraproject.org/en-US/quick-docs/getting-started-with-virtualization/
.. __: https://help.ubuntu.com/community/KVM/Installation
.. __: https://wiki.debian.org/KVM
.. __: https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_virtualization/getting-started-with-virtualization-in-rhel-8_configuring-and-managing-virtualization
.. __: https://doc.opensuse.org/documentation/leap/virtualization/html/book-virt/cha-qemu-host.html
.. __: https://documentation.suse.com/sles/11-SP4/html/SLES-all/book-kvm.html


Configuration
-------------

To enable KVM explicitly, add the following configuration options to the
``/etc/nova/nova.conf`` file:

.. code-block:: ini

   [DEFAULT]
   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = kvm


.. _enable-kvm:

Enable KVM
----------

The following sections outline how to enable KVM based hardware virtualization
on different architectures and platforms.  To perform these steps, you must be
logged in as the ``root`` user.

For x86-based systems
~~~~~~~~~~~~~~~~~~~~~

#. To determine whether the ``svm`` or ``vmx`` CPU extensions are present, run
   this command:

   .. code-block:: console

      # grep -E 'svm|vmx' /proc/cpuinfo

   This command generates output if the CPU is capable of
   hardware-virtualization. Even if output is shown, you might still need to
   enable virtualization in the system BIOS for full support.

   If no output appears, consult your system documentation to ensure that your
   CPU and motherboard support hardware virtualization.  Verify that any
   relevant hardware virtualization options are enabled in the system BIOS.

   The BIOS for each manufacturer is different. If you must enable
   virtualization in the BIOS, look for an option containing the words
   ``virtualization``, ``VT``, ``VMX``, or ``SVM``.

#. To list the loaded kernel modules and verify that the ``kvm`` modules are
   loaded, run this command:

   .. code-block:: console

      # lsmod | grep kvm

   If the output includes ``kvm_intel`` or ``kvm_amd``, the ``kvm`` hardware
   virtualization modules are loaded and your kernel meets the module
   requirements for OpenStack Compute.

   If the output does not show that the ``kvm`` module is loaded, run this
   command to load it:

   .. code-block:: console

      # modprobe -a kvm

   Run the command for your CPU. For Intel, run this command:

   .. code-block:: console

      # modprobe -a kvm-intel

   For AMD, run this command:

   .. code-block:: console

      # modprobe -a kvm-amd

   Because a KVM installation can change user group membership, you might need
   to log in again for changes to take effect.

   If the kernel modules do not load automatically, use the procedures listed
   in these subsections.

If the checks indicate that required hardware virtualization support or kernel
modules are disabled or unavailable, you must either enable this support on the
system or find a system with this support.

.. note::

   Some systems require that you enable VT support in the system BIOS.  If you
   believe your processor supports hardware acceleration but the previous
   command did not produce output, reboot your machine, enter the system BIOS,
   and enable the VT option.

If KVM acceleration is not supported, configure Compute to use a different
hypervisor, such as :ref:`QEMU <compute_qemu>`.

These procedures help you load the kernel modules for Intel-based and AMD-based
processors if they do not load automatically during KVM installation.

.. rubric:: Intel-based processors

If your compute host is Intel-based, run these commands as root to load the
kernel modules:

.. code-block:: console

   # modprobe kvm
   # modprobe kvm-intel

Add these lines to the ``/etc/modules`` file so that these modules load on
reboot:

.. code-block:: console

   kvm
   kvm-intel

.. rubric:: AMD-based processors

If your compute host is AMD-based, run these commands as root to load the
kernel modules:

.. code-block:: console

   # modprobe kvm
   # modprobe kvm-amd

Add these lines to ``/etc/modules`` file so that these modules load on reboot:

.. code-block:: console

   kvm
   kvm-amd

For POWER-based systems
~~~~~~~~~~~~~~~~~~~~~~~

KVM as a hypervisor is supported on POWER system's PowerNV platform.

#. To determine if your POWER platform supports KVM based virtualization run
   the following command:

   .. code-block:: console

      # cat /proc/cpuinfo | grep PowerNV

   If the previous command generates the following output, then CPU supports
   KVM based virtualization.

   .. code-block:: console

      platform: PowerNV

   If no output is displayed, then your POWER platform does not support KVM
   based hardware virtualization.

#. To list the loaded kernel modules and verify that the ``kvm`` modules are
   loaded, run the following command:

   .. code-block:: console

      # lsmod | grep kvm

   If the output includes ``kvm_hv``, the ``kvm`` hardware virtualization
   modules are loaded and your kernel meets the module requirements for
   OpenStack Compute.

   If the output does not show that the ``kvm`` module is loaded, run the
   following command to load it:

   .. code-block:: console

      # modprobe -a kvm

   For PowerNV platform, run the following command:

   .. code-block:: console

      # modprobe -a kvm-hv

   Because a KVM installation can change user group membership, you might need
   to log in again for changes to take effect.

For AArch64-based systems
~~~~~~~~~~~~~~~~~~~~~~~~~

.. todo:: Populate this section.


Configure Compute backing storage
---------------------------------

Backing Storage is the storage used to provide the expanded operating system
image, and any ephemeral storage. Inside the virtual machine, this is normally
presented as two virtual hard disks (for example, ``/dev/vda`` and ``/dev/vdb``
respectively). However, inside OpenStack, this can be derived from one of these
methods: ``lvm``, ``qcow``, ``rbd`` or ``flat``, chosen using the
:oslo.config:option:`libvirt.images_type` option in ``nova.conf`` on the
compute node.

.. note::

   The option ``raw`` is acceptable but deprecated in favor of ``flat``.  The
   Flat back end uses either raw or QCOW2 storage. It never uses a backing
   store, so when using QCOW2 it copies an image rather than creating an
   overlay. By default, it creates raw files but will use QCOW2 when creating a
   disk from a QCOW2 if :oslo.config:option:`force_raw_images` is not set in
   configuration.

QCOW is the default backing store. It uses a copy-on-write philosophy to delay
allocation of storage until it is actually needed. This means that the space
required for the backing of an image can be significantly less on the real disk
than what seems available in the virtual machine operating system.

Flat creates files without any sort of file formatting, effectively creating
files with the plain binary one would normally see on a real disk. This can
increase performance, but means that the entire size of the virtual disk is
reserved on the physical disk.

Local `LVM volumes
<https://en.wikipedia.org/wiki/Logical_Volume_Manager_(Linux)>`__ can also be
used. Set the :oslo.config:option:`libvirt.images_volume_group` configuration
option to the name of the LVM group you have created.


Direct download of images from Ceph
-----------------------------------

When the Glance image service is set up with the Ceph backend and Nova is using
a local ephemeral store (``[libvirt]/images_type!=rbd``), it is possible to
configure Nova to download images directly into the local compute image cache.

With the following configuration, images are downloaded using the RBD export
command instead of using the Glance HTTP API. In some situations, especially
for very large images, this could be substantially faster and can improve the
boot times of instances.

On the Glance API node in ``glance-api.conf``:

.. code-block:: ini

   [DEFAULT]
   show_image_direct_url=true

On the Nova compute node in nova.conf:

.. code-block:: ini

   [glance]
   enable_rbd_download=true
   rbd_user=glance
   rbd_pool=images
   rbd_ceph_conf=/etc/ceph/ceph.conf
   rbd_connect_timeout=5


Nested guest support
--------------------

You may choose to enable support for nested guests --- that is, allow
your Nova instances to themselves run hardware-accelerated virtual
machines with KVM. Doing so requires a module parameter on
your KVM kernel module, and corresponding ``nova.conf`` settings.

Host configuration
~~~~~~~~~~~~~~~~~~

To enable nested KVM guests, your compute node must load the
``kvm_intel`` or ``kvm_amd`` module with ``nested=1``. You can enable
the ``nested`` parameter permanently, by creating a file named
``/etc/modprobe.d/kvm.conf`` and populating it with the following
content:

.. code-block:: none

   options kvm_intel nested=1
   options kvm_amd nested=1

A reboot may be required for the change to become effective.

Nova configuration
~~~~~~~~~~~~~~~~~~

To support nested guests, you must set your
:oslo.config:option:`libvirt.cpu_mode` configuration to one of the following
options:

Host passthrough (``host-passthrough``)
  In this mode, nested virtualization is automatically enabled once
  the KVM kernel module is loaded with nesting support.

  .. code-block:: ini

     [libvirt]
     cpu_mode = host-passthrough

  However, do consider the other implications that
  :doc:`host passthrough </admin/cpu-models>` mode has on compute
  functionality.

Host model (``host-model``)
  In this mode, nested virtualization is automatically enabled once
  the KVM kernel module is loaded with nesting support, **if** the
  matching CPU model exposes the ``vmx`` feature flag to guests by
  default (you can verify this with ``virsh capabilities`` on your
  compute node). If your CPU model does not pass in the ``vmx`` flag,
  you can force it with :oslo.config:option:`libvirt.cpu_model_extra_flags`:

  .. code-block:: ini

     [libvirt]
     cpu_mode = host-model
     cpu_model_extra_flags = vmx

  Again, consider the other implications that apply to the
  :doc:`host model </admin/cpu-models>` mode.

Custom (``custom``)
  In custom mode, the same considerations apply as in host-model mode,
  but you may *additionally* want to ensure that libvirt passes not only
  the ``vmx``, but also the ``pcid`` flag to its guests:

  .. code-block:: ini

     [libvirt]
     cpu_mode = custom
     cpu_models = IvyBridge
     cpu_model_extra_flags = vmx,pcid

More information on CPU models can be found in :doc:`/admin/cpu-models`.

Limitations
~~~~~~~~~~~~

When enabling nested guests, you should be aware of (and inform your
users about) certain limitations that are currently inherent to nested
KVM virtualization. Most importantly, guests using nested
virtualization will, *while nested guests are running*,

* fail to complete live migration;
* fail to resume from suspend.

See `the KVM documentation
<https://www.linux-kvm.org/page/Nested_Guests#Limitations>`_ for more
information on these limitations.


KVM performance tweaks
----------------------

The `VHostNet <http://www.linux-kvm.org/page/VhostNet>`_ kernel module improves
network performance. To load the kernel module, run the following command as
root:

.. code-block:: console

   # modprobe vhost_net


Troubleshooting
---------------

Trying to launch a new virtual machine instance fails with the ``ERROR`` state,
and the following error appears in the ``/var/log/nova/nova-compute.log`` file:

.. code-block:: console

   libvirtError: internal error no supported architecture for os type 'hvm'

This message indicates that the KVM kernel modules were not loaded.

If you cannot start VMs after installation without rebooting, the permissions
might not be set correctly. This can happen if you load the KVM module before
you install ``nova-compute``.  To check whether the group is set to ``kvm``,
run:

.. code-block:: console

   # ls -l /dev/kvm

If it is not set to ``kvm``, run:

.. code-block:: console

   # udevadm trigger
