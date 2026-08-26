.. _intel-tdx:

Intel TDX (Intel Trust Domain Extensions)
==========================================

.. versionadded:: 34.0.0 (Hibiscus)

`Intel Trust Domain Extensions (Intel TDX)`__ is a Confidential Computing
technology from Intel, which provides a hardware-based Trusted Execution
Environment (TEE) to facilitate the deployment of protected virtual machines,
also called *Trust Domains* (TDs). Unlike traditional virtualization,
the contents of a TD's memory and CPU state are protected from inspection
or modification by the hypervisor, the host operating system, and other
software on the platform, including a privileged system and host OS
administrator.

.. __: https://www.intel.com/content/www/us/en/developer/tools/trust-domain-extensions/overview.html

.. _deploying-intel-tdx-capable-infrastructure:

Enabling Intel TDX
------------------

First the operator will need to ensure the following prerequisites are met:

- Currently Intel TDX is only supported when using the libvirt compute
  driver with a :oslo.config:option:`libvirt.virt_type` of ``kvm`` or
  ``qemu``.

- At least one Nova compute host must be Intel TDX capable. From a hardware
  perspective, this means that the host CPU must support Intel TDX. The
  feature was introduced with the 5th Generation Intel Xeon Scalable processors,
  codenamed "Emerald Rapids". Additionally, the host BIOS/firmware must have
  Intel TDX enabled and the software stack must support Intel TDX. Upstream
  support for the basic functionality of Intel TDX was introduced in libvirt
  11.6.0, QEMU 10.1, and KVM with Linux kernel 6.16. Newer Intel TDX features
  and improvements are expected in future releases of these components.

- It is entirely possible for the compute plane to be a mix of hardware
  with and without Intel TDX support. However, per the section on
  `Permanent limitations`_ below, the number of simultaneously running
  TDs will be limited by the number of private keys provided by the
  Intel TDX-capable CPU.

In order for users to be able to use Intel TDX, the operator will need to
perform the following steps:

- A cloud administrator will need to define one or more Intel TDX-enabled
  flavors :ref:`as described below <extra-specs-memory-encryption-tdx>`.

- Configure :oslo.config:option:`libvirt.cpu_mode` to ``host-passthrough``.
  This passes the host CPU model, features, and stepping through to the
  guest exactly as they appear on the host. Intel TDX requires the guest
  to see the full, unmodified feature set of the host CPU, so unlike some
  other hardware-feature-gated functionality, a curated ``custom`` CPU
  model via :oslo.config:option:`libvirt.cpu_models` is not sufficient here.

Additionally the cloud operator should consider the following optional
step:

- Configure :oslo.config:option:`libvirt.hw_machine_type` on all
  Intel TDX-capable compute hosts to include ``x86_64=q35``, so that all
  x86_64 images use the ``q35`` machine type by default, avoiding the
  need to set the ``hw_machine_type`` property on every Intel TDX-bootable
  image.

  .. important::

     :oslo.config:option:`libvirt.hw_machine_type` is a per-host default
     that applies to *every* instance scheduled to that host, not just
     Intel TDX instances, so setting it can affect other workloads
     expecting the ``pc`` machine type. It is recommended to always set
     ``hw_machine_type`` on the image when a feature such as Intel TDX
     requires a specific machine type, and to treat this config option
     as a fallback rather than the primary mechanism, testing carefully
     before applying it beyond a single host or aggregate.

- Configure :oslo.config:option:`libvirt.num_intel_tdx_guests` to represent
  the number of guests a Intel TDX-capable compute node can host concurrently
  with memory encrypted (Intel TDX keys). This option is optional and not
  recommended in most cases, since the limit is normally detected automatically
  via the kernel's misc control group. Automatic detection will be overwritten
  by the value of this option.

.. warning::

  :oslo.config:option:`libvirt.num_intel_tdx_guests` is required for Intel TDX
  functionality if the control group isn't accessible or otherwise doesn't
  report the information from the host (e.g. when running Nova in a container).
  Nova will assume that there are no available Intel TDX keys if it is not
  configured, even if Intel TDX support is detected.

.. note::

  An Intel TDX-aware UEFI firmware (sometimes referred to as "TDVF", built on
  OVMF) must be present on the host. Some distributions ship this as a
  separate package from the regular OVMF firmware (for example, Ubuntu
  provides ``ovmf-inteltdx``).

  Nova uses QEMU's firmware auto-selection, which is based on firmware
  descriptors, to select the matching firmware for TDs. More details on
  these firmware descriptors can be found in the `QEMU firmware descriptor
  documentation`_.

.. _QEMU firmware descriptor documentation:
    https://github.com/qemu/qemu/blob/b428fe036233cbd15d37e3c027ab6ca4d3661a80/docs/interop/firmware.json#L469-L552

.. _extra-specs-memory-encryption-tdx:

Configuring a flavor or image
------------------------------

Once an operator has covered the above steps, users can launch TDs in two ways:

1. By requesting a flavor for which the operator set the
:nova:extra-spec:`hw:mem_encryption` extra spec to ``True`` and the
:nova:extra-spec:`hw:mem_encryption_model` extra spec to ``intel-tdx``.

For example:

  .. code-block:: console

    $ openstack flavor set FLAVOR-NAME \
        --property hw:mem_encryption=true \
        --property hw:mem_encryption_model=intel-tdx

2. By using an image with ``hw_mem_encryption`` set to ``True`` and
``hw_mem_encryption_model`` set to ``intel-tdx``.

For example:

  .. code-block:: console

    $ openstack image set IMAGE-NAME \
        --property hw_mem_encryption=true \
        --property hw_mem_encryption_model=intel-tdx

3. Intel TDX instances can only be booted from images which have the
``hw_firmware_type`` property set to ``uefi``, and only when the
machine type is set to ``q35``.

4. Additionally the guest video device model (``hw_video_model``) needs to be set
to ``none`` to not attach a video device. Intel TDX also requires stateless
firmware, which is enabled by the ``hw_firmware_stateless`` property set to
``true``.

.. note::

  Some distributions ship only a secure boot version of the firmware. In that
  case, the ``os_secure_boot`` property must be set to either ``optional`` or
  ``required`` to select the secure boot version.

Attestation
-----------

.. warning::

    Attestation was tested, but Nova does not actively support attestation and
    provides no guarantees about the functionality of it. Bug reports regarding
    it will not be pursued.

Intel TDX provides a mechanism to remotely verify the integrity of a TD called
*remote attestation*. This process always has two parts: evidence generation and
evidence verification. The first part is always performed by the Intel
TDX-capable host, while the second part is performed by a relying party, which
can be any entity that wants to verify the integrity of a TD, such as a cloud
operator or a customer of a cloud operator.

In the case of Intel TDX, the evidence is called a *TD Quote*, which is
cryptographically protected and contains security-critical information about the
TD and the underlying hardware, e.g., the TD's initial configuration, the
virtual firmware, the CPU state.

TD Quote generation always starts from within the TD, which requests a TD Report
from the CPU. The TD Report is then sent to QEMU, which forwards it to a **Quote
Generation Service (QGS)**. The QGS does certain verifications and generates a
TD Quote from the TD Report. The TD Quote is then sent back to the TD, which can
forward it to a relying party for verification.

Communication between QEMU and the QGS is possible over VSocks and Unix sockets.
As upstream libvirt only supports communication over Unix socket, this is also
the default communication method used by Nova. The current Nova implementation
does not configure the QGS location itself, nor does it currently expose any
option to point at a non-default one. Instead, it exposes the default Unix
socket path used by Intel's tooling.

 .. note::

    At the time of writing, the default Unix socket path is:
    ``/var/run/tdx-qgs/qgs.socket``

Operators must install and enable QGS on every Intel TDX-capable
compute host as part of host setup, before it is added to the compute
plane. This is a manual, host-level step. Nova does not deploy,
manage the lifecycle of, or health-check the QGS on the operator's
behalf.

.. note::

    The QGS only affects whether a TD Quote can be generated. It has no
    bearing on whether a TD starts or continues running, nor does it
    affect the confidentiality or integrity provided by Intel TDX. A
    host with a missing or broken QGS will still successfully boot TDs.
    Conversely, successfully launching a TD does not guarantee that attestation
    is functioning correctly.

.. note::

    Nova does not perform any attestations by itself, it only makes it possible.
    Performing an attestation and verifying the TD Quote is the responsibility
    of the end user. Nova does not provide such means or gate anything on
    whether an attestation attempt succeeds or fails.

Limitations
-----------

Permanent limitations
~~~~~~~~~~~~~~~~~~~~~

The following limitations are expected long-term:

- The maximal number of concurrent TDs is limited by the number of Intel TDX
  private keys supported by the host CPU.

- The guest OS running inside a TD must either support Intel TDX
  natively or an additional layer must be used to provide Intel TDX support
  to a guest OS that does not support Intel TDX natively.

Impermanent limitations
~~~~~~~~~~~~~~~~~~~~~~~~

The following limitations may be removed in the future as the
hardware, firmware, and various layers of software receive new
features:

- Because of missing support in the Linux kernel, TDs cannot yet be
  live-migrated or suspended. At the moment, TDs need to be fully shut down
  before migrating off a Intel TDX host, e.g. if maintenance is required on the
  host.

- For security hardening purposes, TDVF limits the supported features
  of the virtualized platform. As a result, some features that are normally
  available to non-Intel TDX guests may not be available to TDs. For example,
  TDs cannot use the scsi driver.

- Use of spice / VNC is not supported with Intel TDX. Serial console can still
  be used.

Non-limitations
~~~~~~~~~~~~~~~~

For the sake of eliminating any doubt, following actions are expected to work
when Intel TDX is used:

- Cold migration and shelve, since the guest is powered off before the
  operation and no protected TD runtime state needs to be preserved.

- Snapshot, since it only snapshots the disk.

- ``nova evacuate``, since the guest is recreated after it is no longer
  running rather than migrating a live TD.

- Attaching volumes, provided they do not require an IDE bus.

- :doc:`VM guest virtual NUMA <cpu-topologies>`.


References
----------

- `Intel TDX confidential VM support for libvirt driver (Nova
  blueprint)`__

- `Intel TDX overview (Intel documentation)`__

- `Linux kernel Intel TDX documentation`__

.. __: https://blueprints.launchpad.net/nova/+spec/intel-tdx-libvirt-support
.. __: https://www.intel.com/content/www/us/en/developer/tools/trust-domain-extensions/overview.html
.. __: https://www.kernel.org/doc/html/next/x86/tdx.html
