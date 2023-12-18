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

.. _num_memory_encrypted_guests:

- Configure the :oslo.config:option:`libvirt.num_memory_encrypted_guests`
  option in :file:`nova.conf` to represent the number of guests an SEV
  compute node can host concurrently with memory encrypted at the
  hardware level.  For example:

  .. code-block:: ini

     [libvirt]
     num_memory_encrypted_guests = 15

  This option exists because on AMD SEV-capable hardware, the memory
  controller has a fixed number of slots for holding encryption keys,
  one per guest.  For example, at the time of writing, earlier
  generations of hardware only have 15 slots, thereby limiting the
  number of SEV guests which can be run concurrently to 15.  Nova
  needs to track how many slots are available and used in order to
  avoid attempting to exceed that limit in the hardware.

  Since version 8.0.0, libvirt exposes maximum number of SEV guests
  which can run concurrently in its host, so the limit is automatically
  detected using this feature.

  However in case an older version of libvirt is used, it is not possible for
  Nova to programmatically detect the correct value and Nova imposes no limit.
  So this configuration option serves as a stop-gap, allowing the cloud
  operator the option of providing this value manually.

  This option also allows the cloud operator to set the limit lower than
  the actual hard limit.

  .. note::

     If libvirt older than 8.0.0 is used, operators should carefully weigh
     the benefits vs. the risk when deciding whether to use the default of
     ``None`` or manually impose a limit.
     The benefits of using the default are a) immediate convenience since
     nothing needs to be done now, and b) convenience later when upgrading
     compute hosts to future versions of libvirt, since again nothing will
     need to be done for the correct limit to be automatically imposed.
     However the risk is that until auto-detection is implemented, users may
     be able to attempt to launch guests with encrypted memory on hosts which
     have already reached the maximum number of guests simultaneously running
     with encrypted memory.  This risk may be mitigated by other limitations
     which operators can impose, for example if the smallest RAM
     footprint of any flavor imposes a maximum number of simultaneously
     running guests which is less than or equal to the SEV limit.

- Configure :oslo.config:option:`ram_allocation_ratio` on all SEV-capable
  compute hosts to ``1.0``. Use of SEV requires locking guest memory, meaning
  it is not possible to overcommit host memory.

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

These do not inherently cause a preference for SEV-capable hardware,
but for now SEV is the only way of fulfilling the requirement for
memory encryption.  However in the future, support for other
hardware-level guest memory encryption technology such as Intel MKTME
may be added.  If a guest specifically needs to be booted using SEV
rather than any other memory encryption technology, it is possible to
ensure this by setting the :nova:extra-spec:`trait{group}:HW_CPU_X86_AMD_SEV`
extra spec or equivalent image metadata property to ``required``.

In all cases, SEV instances can only be booted from images which have
the ``hw_firmware_type`` property set to ``uefi``, and only when the
machine type is set to ``q35``.  This can be set per image by setting
the image property ``hw_machine_type=q35``, or per compute node by
the operator via :oslo.config:option:`libvirt.hw_machine_type` as
explained above.


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

- The operating system running in an encrypted virtual machine must
  contain SEV support.

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
