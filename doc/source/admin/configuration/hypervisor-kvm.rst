===
KVM
===

.. todo:: This is really installation guide material and should probably be
     moved.

KVM is configured as the default hypervisor for Compute.

.. note::

   This document contains several sections about hypervisor selection.  If you
   are reading this document linearly, you do not want to load the KVM module
   before you install ``nova-compute``.  The ``nova-compute`` service depends
   on qemu-kvm, which installs ``/lib/udev/rules.d/45-qemu-kvm.rules``, which
   sets the correct permissions on the ``/dev/kvm`` device node.

To enable KVM explicitly, add the following configuration options to the
``/etc/nova/nova.conf`` file:

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = kvm

The KVM hypervisor supports the following virtual machine image formats:

* Raw
* QEMU Copy-on-write (QCOW2)
* QED Qemu Enhanced Disk
* VMware virtual machine disk format (vmdk)

This section describes how to enable KVM on your system.  For more information,
see the following distribution-specific documentation:

* `Fedora: Virtualization Getting Started Guide <http://docs.fedoraproject.org/
  en-US/Fedora/22/html/Virtualization_Getting_Started_Guide/index.html>`_
  from the Fedora 22 documentation.
* `Ubuntu: KVM/Installation <https://help.ubuntu.com/community/KVM/
  Installation>`_ from the Community Ubuntu documentation.
* `Debian: Virtualization with KVM <http://static.debian-handbook.info/browse/
  stable/sect.virtualization.html#idp11279352>`_ from the Debian handbook.
* `Red Hat Enterprise Linux: Installing virtualization packages on an existing
  Red Hat Enterprise Linux system <http://docs.redhat.com/docs/en-US/
  Red_Hat_Enterprise_Linux/6/html/Virtualization_Host_Configuration_and_Guest_
  Installation_Guide/sect-Virtualization_Host_Configuration_and_Guest_Installa
  tion_Guide-Host_Installation-Installing_KVM_packages_on_an_existing_Red_Hat_
  Enterprise_Linux_system.html>`_ from the ``Red Hat Enterprise Linux
  Virtualization Host Configuration and Guest Installation Guide``.
* `openSUSE: Installing KVM <http://doc.opensuse.org/documentation/html/
  openSUSE/opensuse-kvm/cha.kvm.requires.html#sec.kvm.requires.install>`_
  from the openSUSE Virtualization with KVM manual.
* `SLES: Installing KVM <https://www.suse.com/documentation/sles-12/book_virt/
  data/sec_vt_installation_kvm.html>`_ from the SUSE Linux Enterprise Server
  ``Virtualization Guide``.

.. _enable-kvm:

Enable KVM
~~~~~~~~~~

The following sections outline how to enable KVM based hardware virtualization
on different architectures and platforms.  To perform these steps, you must be
logged in as the ``root`` user.

For x86 based systems
---------------------

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
hypervisor, such as ``QEMU`` or ``Xen``. See :ref:`compute_qemu` or
:ref:`compute_xen_api` for details.

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

For POWER based systems
-----------------------

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

Configure Compute backing storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backing Storage is the storage used to provide the expanded operating system
image, and any ephemeral storage. Inside the virtual machine, this is normally
presented as two virtual hard disks (for example, ``/dev/vda`` and ``/dev/vdb``
respectively). However, inside OpenStack, this can be derived from one of these
methods: ``lvm``, ``qcow``, ``rbd`` or ``flat``, chosen using the
``images_type`` option in ``nova.conf`` on the compute node.

.. note::

   The option ``raw`` is acceptable but deprecated in favor of ``flat``.  The
   Flat back end uses either raw or QCOW2 storage. It never uses a backing
   store, so when using QCOW2 it copies an image rather than creating an
   overlay. By default, it creates raw files but will use QCOW2 when creating a
   disk from a QCOW2 if ``force_raw_images`` is not set in configuration.

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
used. Set ``images_volume_group = nova_local`` where ``nova_local`` is the name
of the LVM group you have created.

Specify the CPU model of KVM guests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Compute service enables you to control the guest CPU model that is exposed
to KVM virtual machines. Use cases include:

* To maximize performance of virtual machines by exposing new host CPU features
  to the guest

* To ensure a consistent default CPU across all machines, removing reliance of
  variable QEMU defaults

In libvirt, the CPU is specified by providing a base CPU model name (which is a
shorthand for a set of feature flags), a set of additional feature flags, and
the topology (sockets/cores/threads).  The libvirt KVM driver provides a number
of standard CPU model names.  These models are defined in the
``/usr/share/libvirt/cpu_map.xml`` file.  Check this file to determine which
models are supported by your local installation.

Two Compute configuration options in the ``[libvirt]`` group of ``nova.conf``
define which type of CPU model is exposed to the hypervisor when using KVM:
``cpu_mode`` and ``cpu_model``.

The ``cpu_mode`` option can take one of the following values: ``none``,
``host-passthrough``, ``host-model``, and ``custom``.

Host model (default for KVM & QEMU)
-----------------------------------

If your ``nova.conf`` file contains ``cpu_mode=host-model``, libvirt identifies
the CPU model in ``/usr/share/libvirt/cpu_map.xml`` file that most closely
matches the host, and requests additional CPU flags to complete the match. This
configuration provides the maximum functionality and performance and maintains
good reliability and compatibility if the guest is migrated to another host
with slightly different host CPUs.

Host pass through
-----------------

If your ``nova.conf`` file contains ``cpu_mode=host-passthrough``, libvirt
tells KVM to pass through the host CPU with no modifications.  The difference
to host-model, instead of just matching feature flags, every last detail of the
host CPU is matched. This gives the best performance, and can be important to
some apps which check low level CPU details, but it comes at a cost with
respect to migration.  The guest can only be migrated to a matching host CPU.

Custom
------

If your ``nova.conf`` file contains ``cpu_mode=custom``, you can explicitly
specify one of the supported named models using the cpu_model configuration
option. For example, to configure the KVM guests to expose Nehalem CPUs, your
``nova.conf`` file should contain:

.. code-block:: ini

   [libvirt]
   cpu_mode = custom
   cpu_model = Nehalem

None (default for all libvirt-driven hypervisors other than KVM & QEMU)
-----------------------------------------------------------------------

If your ``nova.conf`` file contains ``cpu_mode=none``, libvirt does not specify
a CPU model. Instead, the hypervisor chooses the default model.

Guest agent support
-------------------

Use guest agents to enable optional access between compute nodes and guests
through a socket, using the QMP protocol.

To enable this feature, you must set ``hw_qemu_guest_agent=yes`` as a metadata
parameter on the image you wish to use to create the guest-agent-capable
instances from. You can explicitly disable the feature by setting
``hw_qemu_guest_agent=no`` in the image metadata.

KVM performance tweaks
~~~~~~~~~~~~~~~~~~~~~~

The `VHostNet <http://www.linux-kvm.org/page/VhostNet>`_ kernel module improves
network performance. To load the kernel module, run the following command as
root:

.. code-block:: console

   # modprobe vhost_net

Troubleshoot KVM
~~~~~~~~~~~~~~~~

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
