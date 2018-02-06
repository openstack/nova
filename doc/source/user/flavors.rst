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
  for volume booted instances or for testing purposes.

Ephemeral Disk GB
  Amount of disk space (in gigabytes) to use for the ephemeral partition. This
  property is optional. If unspecified, the value is ``0`` by default.

  Ephemeral disks offer machine local disk storage linked to the lifecycle of a
  VM instance. When a VM is terminated, all data on the ephemeral disk is lost.
  Ephemeral disks are not included in any snapshots.

Swap
  Amount of swap space (in megabytes) to use. This property is optional. If
  unspecified, the value is ``0`` by default.

RXTX Factor
  The receive/transmit factor of any network ports on the instance. This
  property is optional. If unspecified, the value is ``1.0`` by default.

  .. note::

     This property only applies if using the `xen` compute driver with the
     `nova-network` network driver. It will likely be deprecated in a future
     release. `neutron` users should refer to the `neutron QoS
     documentation`__.

     __ https://docs.openstack.org/neutron/latest/admin/config-qos.html

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

.. _flavors-extra-specs:

Extra Specs
~~~~~~~~~~~

.. TODO: Consider adding a table of contents here for the various extra specs
         or make them sub-sections.

.. todo::

   A lot of these need investigation - for example, I can find no reference to
   the ``cpu_shares_level`` option outside of documentation and (possibly)
   useless tests. We should assess which drivers each option actually apply to.

CPU limits
  You can configure the CPU limits with control parameters. For example, to
  configure the I/O limit, use:

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property quota:read_bytes_sec=10240000 \
         --property quota:write_bytes_sec=10240000

  Use these optional parameters to control weight shares, enforcement intervals
  for runtime quotas, and a quota for maximum allowed bandwidth:

  - ``cpu_shares``: Specifies the proportional weighted share for the domain.
    If this element is omitted, the service defaults to the OS provided
    defaults. There is no unit for the value; it is a relative measure based on
    the setting of other VMs. For example, a VM configured with value 2048 gets
    twice as much CPU time as a VM configured with value 1024.

  - ``cpu_shares_level``: On VMware, specifies the allocation level. Can be
    ``custom``, ``high``, ``normal``, or ``low``. If you choose ``custom``, set
    the number of shares using ``cpu_shares_share``.

  - ``cpu_period``: Specifies the enforcement interval (unit: microseconds)
    for QEMU and LXC hypervisors. Within a period, each VCPU of the domain is
    not allowed to consume more than the quota worth of runtime. The value
    should be in range ``[1000, 1000000]``.  A period with value 0 means no
    value.

  - ``cpu_limit``: Specifies the upper limit for VMware machine CPU allocation
    in MHz. This parameter ensures that a machine never uses more than the
    defined amount of CPU time. It can be used to enforce a limit on the
    machine's CPU performance.

  - ``cpu_reservation``: Specifies the guaranteed minimum CPU reservation in
    MHz for VMware. This means that if needed, the machine will definitely get
    allocated the reserved amount of CPU cycles.

  - ``cpu_quota``: Specifies the maximum allowed bandwidth (unit:
    microseconds). A domain with a negative-value quota indicates that the
    domain has infinite bandwidth, which means that it is not bandwidth
    controlled. The value should be in range ``[1000, 18446744073709551]`` or
    less than 0. A quota with value 0 means no value. You can use this feature
    to ensure that all vCPUs run at the same speed. For example:

    .. code-block:: console

       $ openstack flavor set FLAVOR-NAME \
           --property quota:cpu_quota=10000 \
           --property quota:cpu_period=20000

    In this example, an instance of ``FLAVOR-NAME`` can only consume a maximum
    of 50% CPU of a physical CPU computing capability.

Memory limits
  For VMware, you can configure the memory limits with control parameters.

  Use these optional parameters to limit the memory allocation, guarantee
  minimum memory reservation, and to specify shares used in case of resource
  contention:

  - ``memory_limit``: Specifies the upper limit for VMware machine memory
    allocation in MB. The utilization of a virtual machine will not exceed this
    limit, even if there are available resources. This is typically used to
    ensure a consistent performance of virtual machines independent of
    available resources.

  - ``memory_reservation``: Specifies the guaranteed minimum memory reservation
    in MB for VMware. This means the specified amount of memory will definitely
    be allocated to the machine.

  - ``memory_shares_level``: On VMware, specifies the allocation level.  This
    can be ``custom``, ``high``, ``normal`` or ``low``. If you choose
    ``custom``, set the number of shares using ``memory_shares_share``.

  - ``memory_shares_share``: Specifies the number of shares allocated in the
    event that ``custom`` is used. There is no unit for this value. It is a
    relative measure based on the settings for other VMs.  For example:

    .. code-block:: console

       $ openstack flavor set FLAVOR-NAME \
           --property quota:memory_shares_level=custom \
           --property quota:memory_shares_share=15

Disk I/O limits
  For VMware, you can configure the resource limits for disk with control
  parameters.

  Use these optional parameters to limit the disk utilization, guarantee disk
  allocation, and to specify shares used in case of resource contention. This
  allows the VMware driver to enable disk allocations for the running instance.

  - ``disk_io_limit``: Specifies the upper limit for disk utilization in I/O
    per second. The utilization of a virtual machine will not exceed this
    limit, even if there are available resources. The default value is -1 which
    indicates unlimited usage.

  - ``disk_io_reservation``: Specifies the guaranteed minimum disk allocation
    in terms of Input/output Operations Per Second (IOPS).

  - ``disk_io_shares_level``: Specifies the allocation level. This can be
    ``custom``, ``high``, ``normal`` or ``low``.  If you choose custom, set the
    number of shares using ``disk_io_shares_share``.

  - ``disk_io_shares_share``: Specifies the number of shares allocated in the
    event that ``custom`` is used.  When there is resource contention, this
    value is used to determine the resource allocation.

    The example below sets the ``disk_io_reservation`` to 2000 IOPS.

    .. code-block:: console

       $ openstack flavor set FLAVOR-NAME \
           --property quota:disk_io_reservation=2000

Disk tuning
  Using disk I/O quotas, you can set maximum disk write to 10 MB per second for
  a VM user. For example:

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property quota:disk_write_bytes_sec=10485760

  The disk I/O options are:

  - ``disk_read_bytes_sec``
  - ``disk_read_iops_sec``
  - ``disk_write_bytes_sec``
  - ``disk_write_iops_sec``
  - ``disk_total_bytes_sec``
  - ``disk_total_iops_sec``

Bandwidth I/O
  The vif I/O options are:

  - ``vif_inbound_average``
  - ``vif_inbound_burst``
  - ``vif_inbound_peak``
  - ``vif_outbound_average``
  - ``vif_outbound_burst``
  - ``vif_outbound_peak``

  Incoming and outgoing traffic can be shaped independently. The bandwidth
  element can have at most, one inbound and at most, one outbound child
  element. If you leave any of these child elements out, no quality of service
  (QoS) is applied on that traffic direction. So, if you want to shape only the
  network's incoming traffic, use inbound only (and vice versa). Each element
  has one mandatory attribute average, which specifies the average bit rate on
  the interface being shaped.

  There are also two optional attributes (integer): ``peak``, which specifies
  the maximum rate at which a bridge can send data (kilobytes/second), and
  ``burst``, the amount of bytes that can be burst at peak speed (kilobytes).
  The rate is shared equally within domains connected to the network.

  The example below sets network traffic bandwidth limits for existing flavor
  as follows:

  - Outbound traffic:

    - average: 262 Mbps (32768 kilobytes/second)

    - peak: 524 Mbps (65536 kilobytes/second)

    - burst: 65536 kilobytes

  - Inbound traffic:

    - average: 262 Mbps (32768 kilobytes/second)

    - peak: 524 Mbps (65536 kilobytes/second)

    - burst: 65536 kilobytes

  .. code-block:: console

     $ openstack flavor set FLAVOR-NAME \
         --property quota:vif_outbound_average=32768 \
         --property quota:vif_outbound_peak=65536 \
         --property quota:vif_outbound_burst=65536 \
         --property quota:vif_inbound_average=32768 \
         --property quota:vif_inbound_peak=65536 \
         --property quota:vif_inbound_burst=65536

  .. note::

     All the speed limit values in above example are specified in
     kilobytes/second. And burst values are in kilobytes. Values were converted
     using `Data rate units on Wikipedia
     <https://en.wikipedia.org/wiki/Data_rate_units>`_.

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
  - RATE-PERIOD: (integer) Duration of the read period in seconds.

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

  Valid CPU-THREAD-POLICY values are:

  - ``prefer``: (default) The host may or may not have an SMT architecture.
    Where an SMT architecture is present, thread siblings are preferred.
  - ``isolate``: The host must not have an SMT architecture or must emulate a
    non-SMT architecture. If the host does not have an SMT architecture, each
    vCPU is placed on a different core as expected. If the host does have an
    SMT architecture - that is, one or more cores have thread siblings - then
    each vCPU is placed on a different physical core. No vCPUs from other
    guests are placed on the same core. All but one thread sibling on each
    utilized core is therefore guaranteed to be unusable.
  - ``require``: The host must have an SMT architecture. Each vCPU is allocated
    on thread siblings. If the host does not have an SMT architecture, then it
    is not used. If the host has an SMT architecture, but not enough cores with
    free thread siblings are available, then scheduling fails.

  .. note::

     The ``hw:cpu_thread_policy`` option is only valid if ``hw:cpu_policy`` is
     set to ``dedicated``.

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
     ``vcpu_pin_set`` nova configuration option on the host, to choosing a
     correctly configured guest image.

  .. important::

     While most of your instance vCPUs can run with a real-time policy, you must
     mark at least one vCPU as non-real-time, to be used for both non-real-time
     guest processes and emulator overhead (housekeeping) processes.

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
    A coremask indicating which vCPUs **will not** have a real-time policy. This
    should start with a ``^``. For example, a value of ``^0-1`` indicates that
    all vCPUs *except* vCPUs ``0`` and ``1`` will have a real-time policy.

  .. note::

     The ``hw:cpu_realtime_mask`` option is only valid if ``hw:cpu_realtime``
     is set to ``yes``.

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

  Valid THREAD-POLICY values are:

  - ``share``: (default) The emulator threads float across the pCPUs associated
    to the guest.

  - ``isolate``: The emulator threads are isolated on a single pCPU.

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

PCI passthrough
  You can assign PCI devices to a guest by specifying them in the flavor.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property pci_passthrough:alias=ALIAS:COUNT

  Where:

  - ALIAS: (string) The alias which correspond to a particular PCI device class
    as configured in the nova configuration file (see
    :doc:`/configuration/config`).
  - COUNT: (integer) The amount of PCI devices of type ALIAS to be assigned to
    a guest.

Secure Boot
  When your Compute services use the Hyper-V hypervisor, you can enable secure
  boot for Windows and Linux instances.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property os:secure_boot=SECURE_BOOT_OPTION

  Valid ``SECURE_BOOT_OPTION`` values are:

  - ``required``: Enable Secure Boot for instances running with this flavor.
  - ``disabled`` or ``optional``: (default) Disable Secure Boot for instances
    running with this flavor.

Required traits
    Added in the 17.0.0 Queens release.

    Required traits allow specifying a server to build on a compute node with
    the set of traits specified in the flavor. The traits are associated with
    the resource provider that represents the compute node in the Placement
    API. See the resource provider traits API reference for more details:
    https://developer.openstack.org/api-ref/placement/#resource-provider-traits

    The syntax of the extra spec is ``trait:<trait_name>=required``, for
    example:

    - trait:HW_CPU_X86_AVX2=required
    - trait:STORAGE_DISK_SSD=required

    The scheduler will pass required traits to the
    ``GET /allocation_candidates`` endpoint in the Placement API to include
    only resource providers that can satisfy the required traits. Currently
    the only valid value is ``required``. Any other value will be considered
    invalid.

    The FilterScheduler is currently the only scheduler driver that supports
    this feature.
