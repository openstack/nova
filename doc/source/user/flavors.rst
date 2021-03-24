=======
Flavors
=======

In OpenStack, flavors define the compute, memory, and storage capacity of nova
computing instances. To put it simply, a flavor is an available hardware
configuration for a server. It defines the *size* of a virtual server that can
be launched.

.. note::

   Flavors can also determine on which compute host a flavor can be used to
   launch an instance. For information about customizing flavors, refer to
   :doc:`/admin/flavors`.

Overview
--------

A flavor consists of the following parameters:

Flavor ID
  Unique ID (integer or UUID) for the new flavor. This property is required. If
  specifying 'auto', a UUID will be automatically generated.

Name
  Name for the new flavor. This property is required.

  Historically, names were given a format `XX.SIZE_NAME`. These are typically
  not required, though some third party tools may rely on it.

VCPUs
  Number of virtual CPUs to use. This property is required.

Memory MB
  Amount of RAM to use (in megabytes). This property is required.

Root Disk GB
  Amount of disk space (in gigabytes) to use for the root (``/``) partition.
  This property is required.

  The root disk is an ephemeral disk that the base image is copied into. When
  booting from a persistent volume it is not used. The ``0`` size is a special
  case which uses the native base image size as the size of the ephemeral root
  volume. However, in this case the filter scheduler cannot select the compute
  host based on the virtual image size. As a result, ``0`` should only be used
  for volume booted instances or for testing purposes. Volume-backed instances
  can be enforced for flavors with zero root disk via the
  ``os_compute_api:servers:create:zero_disk_flavor`` policy rule.

Ephemeral Disk GB
  Amount of disk space (in gigabytes) to use for the ephemeral partition. This
  property is optional. If unspecified, the value is ``0`` by default.

  Ephemeral disks offer machine local disk storage linked to the lifecycle of a
  VM instance. When a VM is terminated, all data on the ephemeral disk is lost.
  Ephemeral disks are not included in any snapshots.

Swap
  Amount of swap space (in megabytes) to use. This property is optional. If
  unspecified, the value is ``0`` by default.

RXTX Factor (DEPRECATED)
  This value was only applicable when using the ``xen`` compute driver with the
  ``nova-network`` network driver. Since ``nova-network`` has been removed,
  this no longer applies and should not be specified. It will likely be
  removed in a future release. ``neutron`` users should refer to the
  :neutron-doc:`neutron QoS documentation <admin/config-qos.html>`

Is Public
  Boolean value that defines whether the flavor is available to all users or
  private to the project it was created in. This property is optional. In
  unspecified, the value is ``True`` by default.

  By default, a flavor is public and available to all projects. Private flavors
  are only accessible to those on the access list for a given project and are
  invisible to other projects.

Extra Specs
  Key and value pairs that define on which compute nodes a flavor can run.
  These are optional.

  Extra specs are generally used as scheduler hints for more advanced instance
  configuration. The key-value pairs used must correspond to well-known
  options.  For more information on the standardized extra specs available,
  :ref:`see below <flavors-extra-specs>`

Description
  A free form description of the flavor. Limited to 65535 characters in length.
  Only printable characters are allowed. Available starting in
  microversion 2.55.

.. _flavors-extra-specs:

Extra Specs
~~~~~~~~~~~

.. todo::

   This is now documented in :doc:`/configuration/extra-specs`, so this should
   be removed and the documentation moved to those specs.

.. _extra-specs-hardware-video-ram:

Hardware video RAM
  Specify ``hw_video:ram_max_mb`` to control the maximum RAM for the video
  image. Used in conjunction with the ``hw_video_ram`` image property.
  ``hw_video_ram`` must be less than or equal to ``hw_video:ram_max_mb``.

  This is currently supported by the libvirt and the vmware drivers.

  See https://libvirt.org/formatdomain.html#elementsVideo for more information
  on how this is used to set the ``vram`` attribute with the libvirt driver.

  See https://pubs.vmware.com/vi-sdk/visdk250/ReferenceGuide/vim.vm.device.VirtualVideoCard.html
  for more information on how this is used to set the ``videoRamSizeInKB`` attribute with
  the vmware driver.

.. _extra-specs-watchdog-behavior:

Watchdog behavior
  For the libvirt driver, you can enable and set the behavior of a virtual
  hardware watchdog device for each flavor. Watchdog devices keep an eye on the
  guest server, and carry out the configured action, if the server hangs. The
  watchdog uses the i6300esb device (emulating a PCI Intel 6300ESB). If
  ``hw:watchdog_action`` is not specified, the watchdog is disabled.

  To set the behavior, use:

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME --property hw:watchdog_action=ACTION

  Valid ACTION values are:

  - ``disabled``: (default) The device is not attached.
  - ``reset``: Forcefully reset the guest.
  - ``poweroff``: Forcefully power off the guest.
  - ``pause``: Pause the guest.
  - ``none``: Only enable the watchdog; do nothing if the server hangs.

  .. note::

     Watchdog behavior set using a specific image's properties will override
     behavior set using flavors.

.. _extra-specs-random-number-generator:

Random-number generator
  If a random-number generator device has been added to the instance through
  its image properties, the device can be enabled and configured using:

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw_rng:allowed=True \
         --property hw_rng:rate_bytes=RATE-BYTES \
         --property hw_rng:rate_period=RATE-PERIOD

  Where:

  - RATE-BYTES: (integer) Allowed amount of bytes that the guest can read from
    the host's entropy per period.
  - RATE-PERIOD: (integer) Duration of the read period in milliseconds.

.. _extra-specs-performance-monitoring-unit:

Performance Monitoring Unit (vPMU)
  If nova is deployed with the libvirt virt driver and
  :oslo.config:option:`libvirt.virt_type` is set to ``qemu`` or ``kvm``, a
  vPMU can be enabled or disabled for an instance using the ``hw:pmu``
  extra_spec or the ``hw_pmu`` image property.
  The supported values are ``True`` or ``False``. If the vPMU is not
  explicitly enabled or disabled via the flavor or image, its presence is left
  to QEMU to decide.

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME --property hw:pmu=True|False

  The vPMU is used by tools like ``perf`` in the guest to provide more accurate
  information for profiling application and monitoring guest performance.
  For realtime workloads, the emulation of a vPMU can introduce additional
  latency which may be undesirable. If the telemetry it provides is not
  required, such workloads should set ``hw:pmu=False``. For most workloads
  the default of unset or enabling the vPMU ``hw:pmu=True`` will be correct.

.. _extra-specs-cpu-topology:

CPU topology
  For the libvirt driver, you can define the topology of the processors in the
  virtual machine using properties. The properties with ``max`` limit the
  number that can be selected by the user with image properties.

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:cpu_sockets=FLAVOR-SOCKETS \
         --property hw:cpu_cores=FLAVOR-CORES \
         --property hw:cpu_threads=FLAVOR-THREADS \
         --property hw:cpu_max_sockets=FLAVOR-SOCKETS \
         --property hw:cpu_max_cores=FLAVOR-CORES \
         --property hw:cpu_max_threads=FLAVOR-THREADS

  Where:

  - FLAVOR-SOCKETS: (integer) The number of sockets for the guest VM. By
    default, this is set to the number of vCPUs requested.
  - FLAVOR-CORES: (integer) The number of cores per socket for the guest VM. By
    default, this is set to ``1``.
  - FLAVOR-THREADS: (integer) The number of threads per core for the guest VM.
    By default, this is set to ``1``.

.. _extra-specs-cpu-policy:

CPU pinning policy
  For the libvirt driver, you can pin the virtual CPUs (vCPUs) of instances to
  the host's physical CPU cores (pCPUs) using properties. You can further
  refine this by stating how hardware CPU threads in a simultaneous
  multithreading-based (SMT) architecture be used. These configurations will
  result in improved per-instance determinism and performance.

  .. note::

     SMT-based architectures include Intel processors with Hyper-Threading
     technology. In these architectures, processor cores share a number of
     components with one or more other cores. Cores in such architectures are
     commonly referred to as hardware threads, while the cores that a given
     core share components with are known as thread siblings.

  .. note::

     Host aggregates should be used to separate these pinned instances from
     unpinned instances as the latter will not respect the resourcing
     requirements of the former.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:cpu_policy=CPU-POLICY \
         --property hw:cpu_thread_policy=CPU-THREAD-POLICY

  Valid CPU-POLICY values are:

  - ``shared``: (default) The guest vCPUs will be allowed to freely float
    across host pCPUs, albeit potentially constrained by NUMA policy.
  - ``dedicated``: The guest vCPUs will be strictly pinned to a set of host
    pCPUs. In the absence of an explicit vCPU topology request, the drivers
    typically expose all vCPUs as sockets with one core and one thread.  When
    strict CPU pinning is in effect the guest CPU topology will be setup to
    match the topology of the CPUs to which it is pinned. This option implies
    an overcommit ratio of 1.0. For example, if a two vCPU guest is pinned to a
    single host core with two threads, then the guest will get a topology of
    one socket, one core, two threads.
  - ``mixed``: This policy will create an instance combined with the ``shared``
    policy vCPUs and ``dedicated`` policy vCPUs, as a result, some guest vCPUs
    will be freely float across host pCPUs and the rest of guest vCPUs will be
    pinned to host pCPUs. The pinned guest vCPUs are configured using the
    ``hw:cpu_dedicated_mask`` extra spec.

  .. note::

     The ``hw:cpu_dedicated_mask`` option is only valid if ``hw:cpu_policy``
     is set to ``mixed`` and cannot be configured with ``hw:cpu_realtime_mask``
     at the same time.

  Valid CPU-THREAD-POLICY values are:

  - ``prefer``: (default) The host may or may not have an SMT architecture.
    Where an SMT architecture is present, thread siblings are preferred.
  - ``isolate``: The host must not have an SMT architecture or must emulate a
    non-SMT architecture. Hosts that support SMT (by reporting the
    ``HW_CPU_HYPERTHREADING`` trait) are excluded.
  - ``require``: The host must have an SMT architecture and must report the
    ``HW_CPU_HYPERTHREADING`` trait. Each vCPU is allocated on thread siblings.
    If the host does not have an SMT architecture, then it is not used. If the
    host has an SMT architecture, but not enough cores with free thread
    siblings are available, then scheduling fails.

  .. note::

     The ``hw:cpu_thread_policy`` option is valid if ``hw:cpu_policy`` is set
     to ``dedicated`` or ``mixed``.

.. _pci_numa_affinity_policy:

PCI NUMA Affinity Policy
  For the libvirt driver, you can specify the NUMA affinity policy for
  PCI passthrough devices and neutron SR-IOV interfaces via the
  ``hw:pci_numa_affinity_policy`` flavor extra spec or
  ``hw_pci_numa_affinity_policy``  image property. The allowed values are
  ``required``, ``socket``, ``preferred`` or ``legacy`` (default).

  **required**
      This value will mean that nova will boot instances with PCI devices
      **only** if at least one of the NUMA nodes of the instance is associated
      with these PCI devices. It means that if NUMA node info for some PCI
      devices could not be determined, those PCI devices wouldn't be consumable
      by the instance. This provides maximum performance.

  **socket**
      This means that the PCI device must be affined to the same host socket as
      at least one of the guest NUMA nodes. For example, consider a system with
      two sockets, each with two NUMA nodes, numbered node 0 and node 1 on
      socket 0, and node 2 and node 3 on socket 1. There is a PCI device
      affined to node 0. An PCI instance with two guest NUMA nodes and the
      ``socket`` policy can be affined to either:

      * node 0 and node 1
      * node 0 and node 2
      * node 0 and node 3
      * node 1 and node 2
      * node 1 and node 3

      The instance cannot be affined to node 2 and node 3, as neither of those
      are on the same socket as the PCI device. If the other nodes are consumed
      by other instances and only nodes 2 and 3 are available, the instance
      will not boot.

  **preferred**
      This value will mean that ``nova-scheduler`` will choose a compute host
      with minimal consideration for the NUMA affinity of PCI devices.
      ``nova-compute`` will attempt a best effort selection of PCI devices
      based on NUMA affinity, however, if this is not possible then
      ``nova-compute`` will fall back to scheduling on a NUMA node that is not
      associated with the PCI device.

  **legacy**
      This is the default value and it describes the current nova behavior.
      Usually we have information about association of PCI devices with NUMA
      nodes. However, some PCI devices do not provide such information. The
      ``legacy`` value will mean that nova will boot instances with PCI device
      if either:

      * The PCI device is associated with at least one NUMA nodes on which the
        instance will be booted

      * There is no information about PCI-NUMA affinity available

.. _extra-specs-numa-topology:

NUMA topology
  For the libvirt driver, you can define the host NUMA placement for the
  instance vCPU threads as well as the allocation of instance vCPUs and memory
  from the host NUMA nodes. For flavors whose memory and vCPU allocations are
  larger than the size of NUMA nodes in the compute hosts, the definition of a
  NUMA topology allows hosts to better utilize NUMA and improve performance of
  the instance OS.

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:numa_nodes=FLAVOR-NODES \
         --property hw:numa_cpus.N=FLAVOR-CORES \
         --property hw:numa_mem.N=FLAVOR-MEMORY

  Where:

  - FLAVOR-NODES: (integer) The number of host NUMA nodes to restrict execution
    of instance vCPU threads to. If not specified, the vCPU threads can run on
    any number of the host NUMA nodes available.
  - N: (integer) The instance NUMA node to apply a given CPU or memory
    configuration to, where N is in the range ``0`` to ``FLAVOR-NODES - 1``.
  - FLAVOR-CORES: (comma-separated list of integers) A list of instance vCPUs
    to map to instance NUMA node N. If not specified, vCPUs are evenly divided
    among available NUMA nodes.
  - FLAVOR-MEMORY: (integer) The number of MB of instance memory to map to
    instance NUMA node N. If not specified, memory is evenly divided among
    available NUMA nodes.

  .. note::

     ``hw:numa_cpus.N`` and ``hw:numa_mem.N`` are only valid if
     ``hw:numa_nodes`` is set. Additionally, they are only required if the
     instance's NUMA nodes have an asymmetrical allocation of CPUs and RAM
     (important for some NFV workloads).

  .. note::

     The ``N`` parameter is an index of *guest* NUMA nodes and may not
     correspond to *host* NUMA nodes. For example, on a platform with two NUMA
     nodes, the scheduler may opt to place guest NUMA node 0, as referenced in
     ``hw:numa_mem.0`` on host NUMA node 1 and vice versa.  Similarly, the
     integers used for ``FLAVOR-CORES`` are indexes of *guest* vCPUs and may
     not correspond to *host* CPUs. As such, this feature cannot be used to
     constrain instances to specific host CPUs or NUMA nodes.

  .. warning::

     If the combined values of ``hw:numa_cpus.N`` or ``hw:numa_mem.N`` are
     greater than the available number of CPUs or memory respectively, an
     exception is raised.

.. _extra-specs-memory-encryption:

Hardware encryption of guest memory
  If there are compute hosts which support encryption of guest memory
  at the hardware level, this functionality can be requested via the
  ``hw:mem_encryption`` extra spec parameter:

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:mem_encryption=True

.. _extra-specs-realtime-policy:

CPU real-time policy
  For the libvirt driver, you can state that one or more of your instance
  virtual CPUs (vCPUs), though not all of them, run with a real-time policy.
  When used on a correctly configured host, this provides stronger guarantees
  for worst case scheduler latency for vCPUs and is a requirement for certain
  applications.

  .. todo::

     Document the required steps to configure hosts and guests. There are a lot
     of things necessary, from isolating hosts and configuring the
     ``[compute] cpu_dedicated_set`` nova configuration option on the host, to
     choosing a correctly configured guest image.

  .. important::

     While most of your instance vCPUs can run with a real-time policy, you must
     either mark at least one vCPU as non-real-time to be account for emulator
     overhead (housekeeping) or explicitly configure an :ref:`emulator thread
     policy <extra-specs-emulator-threads-policy>`.

  .. important::

     To use this extra spec, you must enable pinned CPUs. Refer to
     :ref:`CPU policy <extra-specs-cpu-policy>` for more information.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:cpu_realtime=CPU-REALTIME-POLICY \
         --property hw:cpu_realtime_mask=CPU-REALTIME-MASK

  Where:

  CPU-REALTIME-POLICY (enum):
    One of:

    - ``no``: (default) The guest vCPUs will not have a real-time policy
    - ``yes``: The guest vCPUs will have a real-time policy

  CPU-REALTIME-MASK (coremask):
    A coremask indicating which vCPUs **will** or, if starting with a ``^``,
    **will not** have a real-time policy. For example, a value of ``0-5``
    indicates that vCPUs ``0`` to ``5`` will have a real-time policy.
    Conversely, a value of ``^0-1`` indicates that all vCPUs *except* vCPUs
    ``0`` and ``1`` will have a real-time policy.

  .. note::

     The ``hw:cpu_realtime_mask`` option is only valid if ``hw:cpu_realtime``
     is set to ``yes``.

  .. versionchanged:: 22.0.0 (Victoria)

     Previously, it was necessary to specify ``hw:cpu_realtime_mask`` when
     ``hw:cpu_realtime`` was set to yes. Starting in Victoria, it is possible
     to omit this when an emulator thread policy is configured using the
     ``hw:emulator_threads_policy`` extra spec.

  .. versionchanged:: 22.0.0 (Victoria)

     Previously, the leading caret was necessary and omitting it would be
     equivalent to not setting the mask, resulting in a failure to spawn
     the instance.

.. _extra-specs-emulator-threads-policy:

Emulator threads policy
  For the libvirt driver, you can assign a separate pCPU to an instance that
  will be used for emulator threads, which are emulator processes not directly
  related to the guest OS. This pCPU will used in addition to the pCPUs used
  for the guest. This is generally required for use with a :ref:`real-time
  workload <extra-specs-realtime-policy>`.

  .. important::

     To use this extra spec, you must enable pinned CPUs. Refer to :ref:`CPU
     policy <extra-specs-cpu-policy>` for more information.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:emulator_threads_policy=THREAD-POLICY

  The expected behavior of emulator threads depends on the value of the
  ``hw:emulator_threads_policy`` flavor extra spec and the value of
  :oslo.config:option:`compute.cpu_shared_set`. It is presented in the
  following table:

  .. list-table::
     :header-rows: 1
     :stub-columns: 1

     * -
       - :oslo.config:option:`compute.cpu_shared_set` set
       - :oslo.config:option:`compute.cpu_shared_set` unset
     * - ``hw:emulator_treads_policy`` unset (default)
       - Pinned to all of the instance's pCPUs
       - Pinned to all of the instance's pCPUs
     * - ``hw:emulator_threads_policy`` = ``share``
       - Pinned to :oslo.config:option:`compute.cpu_shared_set`
       - Pinned to all of the instance's pCPUs
     * - ``hw:emulator_threads_policy`` = ``isolate``
       - Pinned to a single pCPU distinct from the instance's pCPUs
       - Pinned to a single pCPU distinct from the instance's pCPUs

.. _extra-specs-large-pages-allocation:

Large pages allocation
  You can configure the size of large pages used to back the VMs.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:mem_page_size=PAGE_SIZE

  Valid ``PAGE_SIZE`` values are:

  - ``small``: (default) The smallest page size is used. Example: 4 KB on x86.
  - ``large``: Only use larger page sizes for guest RAM. Example: either 2 MB
    or 1 GB on x86.
  - ``any``: It is left up to the compute driver to decide. In this case, the
    libvirt driver might try to find large pages, but fall back to small pages.
    Other drivers may choose alternate policies for ``any``.
  - pagesize: (string) An explicit page size can be set if the workload has
    specific requirements. This value can be an integer value for the page size
    in KB, or can use any standard suffix. Example: ``4KB``, ``2MB``,
    ``2048``, ``1GB``.

  .. note::

     Large pages can be enabled for guest RAM without any regard to whether the
     guest OS will use them or not. If the guest OS chooses not to use huge
     pages, it will merely see small pages as before. Conversely, if a guest OS
     does intend to use huge pages, it is very important that the guest RAM be
     backed by huge pages. Otherwise, the guest OS will not be getting the
     performance benefit it is expecting.

.. _extra-spec-pci-passthrough:

PCI passthrough
  You can assign PCI devices to a guest by specifying them in the flavor.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property pci_passthrough:alias=ALIAS:COUNT

  Where:

  - ALIAS: (string) The alias which correspond to a particular PCI device class
    as configured in the nova configuration file (see
    :oslo.config:option:`pci.alias`).
  - COUNT: (integer) The amount of PCI devices of type ALIAS to be assigned to
    a guest.

.. _extra-specs-hiding-hypervisor-signature:

Hiding hypervisor signature
  Some hypervisors add a signature to their guests. While the presence
  of the signature can enable some paravirtualization features on the
  guest, it can also have the effect of preventing some drivers from
  loading. Hiding the signature by setting this property to true may
  allow such drivers to load and work.

  .. note::

     As of the 18.0.0 Rocky release, this is only supported by the libvirt
     driver.

     Prior to the 21.0.0 Ussuri release, this was called
     ``hide_hypervisor_id``. An alias is provided to provide backwards
     compatibility.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:hide_hypervisor_id=VALUE

  Where:

  - VALUE: (string) 'true' or 'false'. 'false' is equivalent to the
    property not existing.

.. _extra-specs-secure-boot:

Secure Boot
  :doc:`Secure Boot </admin/secure-boot>` can help ensure the bootloader used
  for your instances is trusted, preventing a possible attack vector.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property os:secure_boot=SECURE_BOOT_OPTION

  Valid ``SECURE_BOOT_OPTION`` values are:

  - ``required``: Enable Secure Boot for instances running with this flavor.
  - ``disabled`` or ``optional``: (default) Disable Secure Boot for instances
    running with this flavor.

  .. note::

     Supported by the Hyper-V and libvirt drivers.

  .. versionchanged:: 23.0.0 (Wallaby)

     Added support for secure boot to the libvirt driver.

.. _extra-specs-required-resources:

Custom resource classes and standard resource classes to override
  Specify custom resource classes to require or override quantity values of
  standard resource classes.

  The syntax of the extra spec is ``resources:<resource_class_name>=VALUE``
  (``VALUE`` is integer).
  The name of custom resource classes must start with ``CUSTOM_``.
  Standard resource classes to override are ``VCPU``, ``MEMORY_MB`` or
  ``DISK_GB``. In this case, you can disable scheduling based on standard
  resource classes by setting the value to ``0``.

  For example:

  - ``resources:CUSTOM_BAREMETAL_SMALL=1``
  - ``resources:VCPU=0``

  See :ironic-doc:`Create flavors for use with the Bare Metal service
  <install/configure-nova-flavors>` for more examples.

  .. versionadded:: 16.0.0 (Pike)

.. _extra-specs-required-traits:

Required traits
  Required traits allow specifying a server to build on a compute node with
  the set of traits specified in the flavor. The traits are associated with
  the resource provider that represents the compute node in the Placement
  API. See the resource provider traits API reference for more details:
  https://docs.openstack.org/api-ref/placement/#resource-provider-traits

  The syntax of the extra spec is ``trait:<trait_name>=required``, for
  example:

  - ``trait:HW_CPU_X86_AVX2=required``
  - ``trait:STORAGE_DISK_SSD=required``

  The scheduler will pass required traits to the
  ``GET /allocation_candidates`` endpoint in the Placement API to include
  only resource providers that can satisfy the required traits. In 17.0.0
  the only valid value is ``required``. In 18.0.0 ``forbidden`` is added (see
  below). Any other value will be considered
  invalid.

  The FilterScheduler is currently the only scheduler driver that supports
  this feature.

  Traits can be managed using the `osc-placement plugin`__.

  __ https://docs.openstack.org/osc-placement/latest/index.html

  .. versionadded:: 17.0.0 (Queens)

.. _extra-specs-forbidden-traits:

Forbidden traits
  Forbidden traits are similar to required traits, described above, but
  instead of specifying the set of traits that must be satisfied by a compute
  node, forbidden traits must **not** be present.

  The syntax of the extra spec is ``trait:<trait_name>=forbidden``, for
  example:

  - ``trait:HW_CPU_X86_AVX2=forbidden``
  - ``trait:STORAGE_DISK_SSD=forbidden``

  The FilterScheduler is currently the only scheduler driver that supports
  this feature.

  Traits can be managed using the `osc-placement plugin`__.

  __ https://docs.openstack.org/osc-placement/latest/index.html

  .. versionadded:: 18.0.0 (Rocky)

.. _extra-specs-numbered-resource-groupings:

Numbered groupings of resource classes and traits
  Specify numbered groupings of resource classes and traits.

  The syntax is as follows (``N`` and ``VALUE`` are integers):

  .. parsed-literal::

    resources\ *N*:*<resource_class_name>*\ =\ *VALUE*
    trait\ *N*:*<trait_name>*\ =required

  A given numbered ``resources`` or ``trait`` key may be repeated to
  specify multiple resources/traits in the same grouping,
  just as with the un-numbered syntax.

  Specify inter-group affinity policy via the ``group_policy`` key,
  which may have the following values:

  * ``isolate``: Different numbered request groups will be satisfied by
    *different* providers.
  * ``none``: Different numbered request groups may be satisfied
    by different providers *or* common providers.

  .. note::

      If more than one group is specified then the ``group_policy`` is
      mandatory in the request. However such groups might come from other
      sources than flavor extra_spec (e.g. from Neutron ports with QoS
      minimum bandwidth policy). If the flavor does not specify any groups
      and ``group_policy`` but more than one group is coming from other
      sources then nova will default the ``group_policy`` to ``none`` to
      avoid scheduler failure.

  For example, to create a server with the following VFs:

  * One SR-IOV virtual function (VF) on NET1 with bandwidth 10000 bytes/sec
  * One SR-IOV virtual function (VF) on NET2 with bandwidth 20000 bytes/sec
    on a *different* NIC with SSL acceleration

  It is specified in the extra specs as follows::

    resources1:SRIOV_NET_VF=1
    resources1:NET_EGRESS_BYTES_SEC=10000
    trait1:CUSTOM_PHYSNET_NET1=required
    resources2:SRIOV_NET_VF=1
    resources2:NET_EGRESS_BYTES_SEC:20000
    trait2:CUSTOM_PHYSNET_NET2=required
    trait2:HW_NIC_ACCEL_SSL=required
    group_policy=isolate

  See `Granular Resource Request Syntax`__ for more details.

  __ https://specs.openstack.org/openstack/nova-specs/specs/rocky/implemented/granular-resource-requests.html

  .. versionadded:: 18.0.0 (Rocky)

.. _vtpm-flavor:

Emulated Virtual TPM
  If supported by the compute host, you can add an :doc:`emulated trusted
  platform module (TPM) </admin/emulated-tpm>` to the guest OS.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property hw:tpm_version=$VERSION \
         --property hw:tpm_model=$MODEL

  ``hw:tpm_version`` is required to enable support. Valid ``$VERSION`` values
  are:

  - ``1.2`` : Selects TPM version 1.2 support.
  - ``2.0`` : Selects TPM version 2.0 support.

  ``hw:tpm_model`` is optional. Valid ``$MODEL`` values are:

  - ``tpm-tis``: Selects TIS device model. This is the default value.
  - ``tpm-crb``: Selects CRB device model. Only valid for TPM version 2.0.
