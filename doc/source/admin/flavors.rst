=======
Flavors
=======

Admin users can use the :command:`openstack flavor` command to customize and
manage flavors. To see information for this command, run:

.. code-block:: console

    $ openstack flavor --help
    Command "flavor" matches:
      flavor create
      flavor delete
      flavor list
      flavor set
      flavor show
      flavor unset

.. note::

   Configuration rights can be delegated to additional users by redefining
   the access controls for ``os_compute_api:os-flavor-manage`` in
   ``/etc/nova/policy.json`` on the ``nova-api`` server.

Flavors define these elements:

.. todo:: This would be much easier to read as a list-table or similar

+-------------+---------------------------------------------------------------+
| Element     | Description                                                   |
+=============+===============================================================+
| Name        | A descriptive name. XX.SIZE_NAME is typically not required,   |
|             | though some third party tools may rely on it.                 |
+-------------+---------------------------------------------------------------+
| Memory MB   | Instance memory in megabytes.                                 |
+-------------+---------------------------------------------------------------+
| Disk        | Virtual root disk size in gigabytes. This is an ephemeral di\ |
|             | sk that the base image is copied into. When booting from a p\ |
|             | ersistent volume it is not used. The "0" size is a special c\ |
|             | ase which uses the native base image size as the size of the  |
|             | ephemeral root volume. However, in this case the filter       |
|             | scheduler cannot select the compute host based on the virtual |
|             | image size. Therefore 0 should only be used for volume booted |
|             | instances or for testing purposes.                            |
+-------------+---------------------------------------------------------------+
| Ephemeral   | Specifies the size of a secondary ephemeral data disk. This   |
|             | is an empty, unformatted disk and exists only for the life o\ |
|             | f the instance. Default value is ``0``.                       |
+-------------+---------------------------------------------------------------+
| Swap        | Optional swap space allocation for the instance. Default      |
|             | value is ``0``.                                               |
+-------------+---------------------------------------------------------------+
| VCPUs       | Number of virtual CPUs presented to the instance.             |
+-------------+---------------------------------------------------------------+
| RXTX Factor | Optional property allows created servers to have a different  |
|             | bandwidth cap than that defined in the network they are att\  |
|             | ached to. This factor is multiplied by the rxtx_base propert\ |
|             | y of the network. Default value is ``1.0``. That is, the same |
|             | as attached network. This parameter is only available for Xen |
|             | or NSX based systems.                                         |
+-------------+---------------------------------------------------------------+
| Is Public   | Boolean value, whether flavor is available to all users or p\ |
|             | rivate to the project it was created in. Defaults to ``True``.|
+-------------+---------------------------------------------------------------+
| Extra Specs | Key and value pairs that define on which compute nodes a fla\ |
|             | vor can run. These pairs must match corresponding pairs on t\ |
|             | he compute nodes. Use to implement special resources, such a\ |
|             | s flavors that run on only compute nodes with GPU hardware.   |
+-------------+---------------------------------------------------------------+

.. note::

    Flavor customization can be limited by the hypervisor in use. For example
    the libvirt driver enables quotas on CPUs available to a VM, disk tuning,
    bandwidth I/O, watchdog behavior, random number generator device control,
    and instance VIF traffic control.

Is Public
~~~~~~~~~

Flavors can be assigned to particular projects. By default, a flavor is public
and available to all projects. Private flavors are only accessible to those on
the access list and are invisible to other projects. To create and assign a
private flavor to a project, run this command:

.. code-block:: console

   $ openstack flavor create --private p1.medium --id auto --ram 512 --disk 40 --vcpus 4

Extra Specs
~~~~~~~~~~~

CPU limits
  You can configure the CPU limits with control parameters with the ``nova``
  client. For example, to configure the I/O limit, use:

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
     using 'Data rate units on Wikipedia
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
