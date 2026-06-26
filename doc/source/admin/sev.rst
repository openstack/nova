.. _amd-sev:

AMD SEV (Secure Encrypted Virtualization)
=========================================

.. versionadded:: 20.0.0 (Train)

`Secure Encrypted Virtualization (SEV)`__ is a technology from AMD which
enables the memory for a VM to be encrypted with a key unique to the VM.
SEV is particularly applicable to cloud computing since it can reduce the
amount of trust VMs need to place in the hypervisor and administrator of
their host system.

.. __: https://developer.amd.com/sev/


.. _deploying-sev-capable-infrastructure:

Enabling SEV
------------

First the operator will need to ensure the following prerequisites are met:

- Currently SEV is only supported when using the libvirt compute driver with a
  :oslo.config:option:`libvirt.virt_type` of ``kvm`` or ``qemu``.

- At least one of the Nova compute hosts must be AMD hardware capable
  of supporting SEV.  It is entirely possible for the compute plane to
  be a mix of hardware which can and cannot support SEV, although as
  per the section on `Permanent limitations`_ below, the maximum
  number of simultaneously running guests with SEV will be limited by
  the quantity and quality of SEV-capable hardware available.

In order for users to be able to use SEV, the operator will need to
perform the following steps:

- Ensure that sufficient memory is reserved on the SEV compute hosts
  for host-level services to function correctly at all times.  This is
  particularly important when hosting SEV-enabled guests, since they
  pin pages in RAM, preventing any memory overcommit which may be in
  normal operation on other compute hosts.

  It is `recommended`__ to achieve this by configuring an ``rlimit`` at
  the ``/machine.slice`` top-level ``cgroup`` on the host, with all VMs
  placed inside that.  (For extreme detail, see `this discussion on the
  spec`__.)

  __ http://specs.openstack.org/openstack/nova-specs/specs/train/approved/amd-sev-libvirt-support.html#memory-reservation-solutions
  __ https://review.opendev.org/#/c/641994/2/specs/train/approved/amd-sev-libvirt-support.rst@167

  An alternative approach is to configure the
  :oslo.config:option:`reserved_host_memory_mb` option in the
  ``[DEFAULT]`` section of :file:`nova.conf`, based on the expected
  maximum number of SEV guests simultaneously running on the host, and
  the details provided in `an earlier version of the AMD SEV spec`__
  regarding memory region sizes, which cover how to calculate it
  correctly.

  __ https://specs.openstack.org/openstack/nova-specs/specs/stein/approved/amd-sev-libvirt-support.html#proposed-change

  See `the Memory Locking and Accounting section of the AMD SEV spec`__
  and `previous discussion for further details`__.

  __ http://specs.openstack.org/openstack/nova-specs/specs/train/approved/amd-sev-libvirt-support.html#memory-locking-and-accounting
  __ https://review.opendev.org/#/c/641994/2/specs/train/approved/amd-sev-libvirt-support.rst@167

- A cloud administrator will need to define one or more SEV-enabled
  flavors :ref:`as described below <extra-specs-memory-encryption>`, unless it
  is sufficient for users to define SEV-enabled images.

Additionally the cloud operator should consider the following optional
steps:

- Configure :oslo.config:option:`ram_allocation_ratio` on all SEV-capable
  compute hosts to ``1.0``. Use of SEV requires that guest memory is not
  swapped out to disks, meaning it is not possible to overcommit host memory.

  Alternatively, you can explicitly configure small pages for instances using
  the :nova:extra-spec:`hw:mem_page_size` flavor extra spec and equivalent
  image metadata property. For more information, see :doc:`huge-pages`.

- Configure :oslo.config:option:`libvirt.hw_machine_type` on all
  SEV-capable compute hosts to include ``x86_64=q35``, so that all
  x86_64 images use the ``q35`` machine type by default.  (Currently
  Nova defaults to the ``pc`` machine type for the ``x86_64``
  architecture, although `it is expected that this will change in the
  future`__.)

  Changing the default from ``pc`` to ``q35`` makes the creation and
  configuration of images by users more convenient by removing the
  need for the ``hw_machine_type`` property to be set to ``q35`` on
  every image for which SEV booting is desired.

  .. caution::

     Consider carefully whether to set this option.  It is
     particularly important since a limitation of the implementation
     prevents the user from receiving an error message with a helpful
     explanation if they try to boot an SEV guest when neither this
     configuration option nor the image property are set to select
     a ``q35`` machine type.

     On the other hand, setting it to ``q35`` may have other
     undesirable side-effects on other images which were expecting to
     be booted with ``pc``, so it is suggested to set it on a single
     compute node or aggregate, and perform careful testing of typical
     images before rolling out the setting to all SEV-capable compute
     hosts.

  __ https://bugs.launchpad.net/nova/+bug/1780138

- Configure :oslo.config:option:`libvirt.cpu_mode` and
  :oslo.config:option:`libvirt.cpu_models` properly so that the cpu model for
  instances is capable to support the required SEV feature.

  .. note::

     It is also required that the appropriate QEMU firmware descriptor file is
     present in the host operating system. These files are provided by
     the ovmf package from distributions in most cases, but it is known that
     Ubuntu 26.04 does not yet provide the content required to launch SEV-SNP
     instances properly. See `bug 2160129
     <https://bugs.launchpad.net/ubuntu/+source/edk2/+bug/2160129>`_ for
     details.

.. _extra-specs-memory-encryption:

Configuring a flavor or image
-----------------------------

Once an operator has covered the above steps, users can launch SEV
instances either by requesting a flavor for which the operator set the
:nova:extra-spec:`hw:mem_encryption` extra spec to ``True``, or by using an
image with the ``hw_mem_encryption`` property set to ``True``. For example, to
enable SEV for a flavor:

.. code-block:: console

   $ openstack flavor set FLAVOR-NAME \
       --property hw:mem_encryption=true

It is also possible to use SEV-ES or SEV-SNP, instead of SEV, by setting
the :nova:extra-spec:`hw:mem_encryption_model` extra spec, or by using an image
with the ``hw_mem_encryption_model`` property. Use ``amd-sev-es`` for SEV-ES
and ``amd-sev-snp`` for SEV-SNP. In case the extra spec and the property are
unset or set to ``amd-sev`` then SEV is used.

In all cases, SEV instances can only be booted from images which have
the ``hw_firmware_type`` property set to ``uefi``, and only when the
machine type is set to ``q35``.  This can be set per image by setting
the image property ``hw_machine_type=q35``, or per compute node by
the operator via :oslo.config:option:`libvirt.hw_machine_type` as
explained above. SEV-SNP instances also require stateless firmware, which is
enabled by the ``hw_firmware_stateless`` property set to ``true``.


Limitations
-----------

Impermanent limitations
~~~~~~~~~~~~~~~~~~~~~~~

The following limitations may be removed in the future as the
hardware, firmware, and various layers of software receive new
features:

- SEV-encrypted VMs cannot yet be live-migrated or suspended,
  therefore they will need to be fully shut down before migrating off
  an SEV host, e.g. if maintenance is required on the host.

- SEV-encrypted VMs cannot contain directly accessible host devices
  (PCI passthrough).  So for example mdev vGPU support will not
  currently work.  However technologies based on `vhost-user`__ should
  work fine.

  __ https://wiki.qemu.org/Features/VirtioVhostUser

- The boot disk of SEV-encrypted VMs can only be ``virtio``.
  (``virtio-blk`` is typically the default for libvirt disks on x86,
  but can also be explicitly set e.g. via the image property
  ``hw_disk_bus=virtio``). Valid alternatives for the disk
  include using ``hw_disk_bus=scsi`` with
  ``hw_scsi_model=virtio-scsi`` , or ``hw_disk_bus=sata``.

Permanent limitations
~~~~~~~~~~~~~~~~~~~~~

The following limitations are expected long-term:

- The number of SEV guests allowed to run concurrently will always be
  limited.  `On the first generation of EPYC machines it will be
  limited to 15 guests`__; however this limit becomes much higher with
  the second generation (Rome).

  __ https://www.redhat.com/archives/libvir-list/2019-January/msg00652.html

- The number of SEV-ES guests and SEV-SNP guests allowed to run concurrently
  will always be limited. The total ASID slots are divided into the two pools
  (one for SEV and the other for SEV-ES and SEV-SNP), according to
  the ``Minimum ASID for SEV`` option in BIOS.

- The operating system running in an encrypted virtual machine must
  contain SEV support.

- SEV-ES and SEV-SNP are mutually-exclusive in a single host, due to firmware
  update to resolve
  `CVE-2025-48514 <https://nvd.nist.gov/vuln/detail/CVE-2025-48514>`_ .

Non-limitations
~~~~~~~~~~~~~~~

For the sake of eliminating any doubt, the following actions are *not*
expected to be limited when SEV encryption is used:

- Cold migration or shelve, since they power off the VM before the
  operation at which point there is no encrypted memory (although this
  could change since there is work underway to add support for `PMEM
  <https://pmem.io/>`_)

- Snapshot, since it only snapshots the disk

- ``nova evacuate`` (despite the name, more akin to resurrection than
  evacuation), since this is only initiated when the VM is no longer
  running

- Attaching any volumes, as long as they do not require attaching via
  an IDE bus

- Use of spice / VNC / serial / RDP consoles

- :doc:`VM guest virtual NUMA <cpu-topologies>`


References
----------

- `libvirt driver launching AMD SEV-encrypted instances (spec)`__

.. __: http://specs.openstack.org/openstack/nova-specs/specs/train/approved/amd-sev-libvirt-support.html
