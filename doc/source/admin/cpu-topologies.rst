==============
CPU topologies
==============

The NUMA topology and CPU pinning features in OpenStack provide high-level
control over how instances run on hypervisor CPUs and the topology of virtual
CPUs available to instances. These features help minimize latency and maximize
performance.

.. include:: /common/numa-live-migration-warning.txt

SMP, NUMA, and SMT
------------------

Symmetric multiprocessing (SMP)
  SMP is a design found in many modern multi-core systems. In an SMP system,
  there are two or more CPUs and these CPUs are connected by some interconnect.
  This provides CPUs with equal access to system resources like memory and
  input/output ports.

Non-uniform memory access (NUMA)
  NUMA is a derivative of the SMP design that is found in many multi-socket
  systems. In a NUMA system, system memory is divided into cells or nodes that
  are associated with particular CPUs. Requests for memory on other nodes are
  possible through an interconnect bus. However, bandwidth across this shared
  bus is limited. As a result, competition for this resource can incur
  performance penalties.

Simultaneous Multi-Threading (SMT)
  SMT is a design complementary to SMP. Whereas CPUs in SMP systems share a bus
  and some memory, CPUs in SMT systems share many more components. CPUs that
  share components are known as thread siblings.  All CPUs appear as usable
  CPUs on the system and can execute workloads in parallel. However, as with
  NUMA, threads compete for shared resources.

Non-Uniform I/O Access (NUMA I/O)
  In a NUMA system, I/O to a device mapped to a local memory region is more
  efficient than I/O to a remote device. A device connected to the same socket
  providing the CPU and memory offers lower latencies for I/O operations due to
  its physical proximity. This generally manifests itself in devices connected
  to the PCIe bus, such as NICs or vGPUs, but applies to any device support
  memory-mapped I/O.

In OpenStack, SMP CPUs are known as *cores*, NUMA cells or nodes are known as
*sockets*, and SMT CPUs are known as *threads*. For example, a quad-socket,
eight core system with Hyper-Threading would have four sockets, eight cores per
socket and two threads per core, for a total of 64 CPUs.

PCPU and VCPU
-------------

PCPU
  Resource class representing an amount of dedicated CPUs for a single guest.

VCPU
  Resource class representing a unit of CPU resources for a single guest
  approximating the processing power of a single physical processor.

.. _numa-topologies:

Customizing instance NUMA placement policies
--------------------------------------------

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver.

When running workloads on NUMA hosts, it is important that the vCPUs executing
processes are on the same NUMA node as the memory used by these processes.
This ensures all memory accesses are local to the node and thus do not consume
the limited cross-node memory bandwidth, adding latency to memory accesses.
Similarly, large pages are assigned from memory and benefit from the same
performance improvements as memory allocated using standard pages. Thus, they
also should be local. Finally, PCI devices are directly associated with
specific NUMA nodes for the purposes of DMA. Instances that use PCI or SR-IOV
devices should be placed on the NUMA node associated with these devices.

NUMA topology can exist on both the physical hardware of the host and the
virtual hardware of the instance. In OpenStack, when booting a process, the
hypervisor driver looks at the NUMA topology field of both the instance and
the host it is being booted on, and uses that information to generate an
appropriate configuration.

By default, an instance floats across all NUMA nodes on a host. NUMA awareness
can be enabled implicitly through the use of huge pages or pinned CPUs or
explicitly through the use of flavor extra specs or image metadata. If the
instance has requested a specific NUMA topology, compute will try to pin the
vCPUs of different NUMA cells on the instance to the corresponding NUMA cells
on the host. It will also expose the NUMA topology of the instance to the
guest OS.

In all cases where NUMA awareness is used, the ``NUMATopologyFilter``
filter must be enabled. Details on this filter are provided in
:doc:`/admin/scheduling`.

The host's NUMA node(s) used are chosen based on some logic and controlled by
``packing_host_numa_cells_allocation_strategy`` configuration variable in
nova.conf. By default ``packing_host_numa_cells_allocation_strategy``
variable is set to ``True``. It leads to attempt to chose NUMA node(s) with
less amount of free resources (or in other words **more used** NUMA nodes)
first. It is so-called "pack" strategy - we try to place as much as possible
load at **more used** host's NUMA node until it will be completely exhausted.
And only after we will choose **most used** host's NUMA node from the rest
available nodes on host. "Spread" strategy is reverse to "pack" strategy.
The NUMA node(s) with **more free** resources will be used first. So "spread"
strategy will try to balance load between all NUMA nodes and keep number of
free resources on all NUMA nodes as more equal as possible.

.. caution::

    Host's NUMA nodes are placed in list and list is sorted based on strategy
    chosen and resource available in each NUMA node. Sorts are performed on
    same list one after another, so the last sort implemented is the sort
    with most priority.

The python performed so-called stable sort. It means that each sort executed
on same list will change order of list items only if item's property we sort on
differs. If this properties in all list's items are equal than elements order
will not changed.

Sorts are performed on host's NUMA nodes list in the following order:

*  sort based on available memory on node(first sort-less priority)
*  sort based on cpu usage (in case of shared CPUs requested by guest
   VM topology) or free pinned cpus otherwise.
*  sort based on number of free PCI device on node(last sort-top priority)

Top sorting priority is for host's NUMA nodes with PCI devices attached. If VM
requested PCI device(s) logic **always** puts host's NUMA nodes with more PCI
devices at the beginning of the host's NUMA nodes list. If PCI devices isn't
requested by VM than NUMA nodes with no (or less) PCI device available will be
placed at the beginning of the list.

.. caution::

   The described logic for PCI devices is used **both** for "pack" and "spread"
   strategies. It is done to keep backward compatibility with previous nova
   versions.


During "pack" logic implementation rest (two) sorts are performed with sort
order to move NUMA nodes with more available resources (CPUs and memory) at the
END of host's NUMA nodes list. Sort based on memory is the first sort
implemented and has least priority.

During "spread" logic implementation rest (two) sorts are performed with sort
order to move NUMA nodes with more available resources (CPUs and memory) at the
BEGINNING of host's NUMA nodes list. Sort based on memory is the first sort
implemented and has least priority.

Finally resulting list (after all sorts) is passed next and attempts to place
VM's NUMA node to host's NUMA node are performed starting from the first
host's NUMA node in list.

.. caution::

   Inadequate per-node resources will result in scheduling failures. Resources
   that are specific to a node include not only CPUs and memory, but also PCI
   and SR-IOV resources. It is not possible to use multiple resources from
   different nodes without requesting a multi-node layout. As such, it may be
   necessary to ensure PCI or SR-IOV resources are associated with the same
   NUMA node or force a multi-node layout.

When used, NUMA awareness allows the operating system of the instance to
intelligently schedule the workloads that it runs and minimize cross-node
memory bandwidth. To configure guest NUMA nodes, you can use the
:nova:extra-spec:`hw:numa_nodes` flavor extra spec.
For example, to restrict an instance's vCPUs to a single host NUMA node,
run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:numa_nodes=1

Some workloads have very demanding requirements for memory access latency or
bandwidth that exceed the memory bandwidth available from a single NUMA node.
For such workloads, it is beneficial to spread the instance across multiple
host NUMA nodes, even if the instance's RAM/vCPUs could theoretically fit on a
single NUMA node. To force an instance's vCPUs to spread across two host NUMA
nodes, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:numa_nodes=2

The allocation of instance vCPUs and memory from different host NUMA nodes can
be configured. This allows for asymmetric allocation of vCPUs and memory, which
can be important for some workloads. You can configure the allocation of
instance vCPUs and memory across each **guest** NUMA node using the
:nova:extra-spec:`hw:numa_cpus.{num}` and :nova:extra-spec:`hw:numa_mem.{num}`
extra specs respectively.
For example, to spread the 6 vCPUs and 6 GB of memory
of an instance across two NUMA nodes and create an asymmetric 1:2 vCPU and
memory mapping between the two nodes, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:numa_nodes=2
   # configure guest node 0
   $ openstack flavor set $FLAVOR \
     --property hw:numa_cpus.0=0,1 \
     --property hw:numa_mem.0=2048
   # configure guest node 1
   $ openstack flavor set $FLAVOR \
     --property hw:numa_cpus.1=2,3,4,5 \
     --property hw:numa_mem.1=4096

.. note::

   The ``{num}`` parameter is an index of *guest* NUMA nodes and may not
   correspond to *host* NUMA nodes. For example, on a platform with two NUMA
   nodes, the scheduler may opt to place guest NUMA node 0, as referenced in
   ``hw:numa_mem.0`` on host NUMA node 1 and vice versa.  Similarly, the
   CPUs bitmask specified in the value for ``hw:numa_cpus.{num}`` refer to
   *guest* vCPUs and may not correspond to *host* CPUs. As such, this feature
   cannot be used to constrain instances to specific host CPUs or NUMA nodes.

.. warning::

   If the combined values of ``hw:numa_cpus.{num}`` or ``hw:numa_mem.{num}``
   are greater than the available number of CPUs or memory respectively, an
   exception will be raised.

For more information about the syntax for ``hw:numa_nodes``, ``hw:numa_cpus.N``
and ``hw:num_mem.N``, refer to :doc:`/configuration/extra-specs`.


.. _cpu-pinning-policies:

Customizing instance CPU pinning policies
-----------------------------------------

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver and requires :ref:`some host configuration
   <configure-libvirt-pinning>` for this to work.

.. note::

   There is no correlation required between the NUMA topology exposed in the
   instance and how the instance is actually pinned on the host. This is by
   design. See this `invalid bug
   <https://bugs.launchpad.net/nova/+bug/1466780>`_ for more information.

By default, instance vCPU processes are not assigned to any particular host
CPU, instead, they float across host CPUs like any other process. This allows
for features like overcommitting of CPUs. In heavily contended systems, this
provides optimal system performance at the expense of performance and latency
for individual instances.

Some workloads require real-time or near real-time behavior, which is not
possible with the latency introduced by the default CPU policy. For such
workloads, it is beneficial to control which host CPUs are bound to an
instance's vCPUs. This process is known as pinning. No instance with pinned
CPUs can use the CPUs of another pinned instance, thus preventing resource
contention between instances.

CPU pinning policies can be used to determine whether an instance should be
pinned or not. They can be configured using the
:nova:extra-spec:`hw:cpu_policy` extra spec and equivalent image metadata
property. There are three policies: ``dedicated``, ``mixed`` and
``shared`` (the default). The ``dedicated`` CPU policy is used to specify
that all CPUs of an instance should use pinned CPUs. To configure a flavor to
use the ``dedicated`` CPU policy, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:cpu_policy=dedicated

This works by ensuring ``PCPU`` allocations are used instead of ``VCPU``
allocations. As such, it is also possible to request this resource type
explicitly. To configure this, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property resources:PCPU=N

(where ``N`` is the number of vCPUs defined in the flavor).

.. note::

   It is not currently possible to request ``PCPU`` and ``VCPU`` resources in
   the same instance.

The ``shared`` CPU policy is used to specify that an instance **should not**
use pinned CPUs. To configure a flavor to use the ``shared`` CPU policy, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:cpu_policy=shared

The ``mixed`` CPU policy is used to specify that an instance use pinned CPUs
along with unpinned CPUs. The instance pinned CPU could be specified in the
:nova:extra-spec:`hw:cpu_dedicated_mask` or, if :doc:`real-time <real-time>` is
enabled, in the :nova:extra-spec:`hw:cpu_realtime_mask` extra spec. For
example, to configure a flavor to use the ``mixed`` CPU policy with 4 vCPUs in
total and the first 2 vCPUs as pinned CPUs, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --vcpus=4 \
     --property hw:cpu_policy=mixed \
     --property hw:cpu_dedicated_mask=0-1

To configure a flavor to use the ``mixed`` CPU policy with 4 vCPUs in total and
the first 2 vCPUs as pinned **real-time** CPUs, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --vcpus=4 \
     --property hw:cpu_policy=mixed \
     --property hw:cpu_realtime=yes \
     --property hw:cpu_realtime_mask=0-1

.. note::

   For more information about the syntax for ``hw:cpu_policy``,
   ``hw:cpu_dedicated_mask``, ``hw:realtime_cpu`` and ``hw:cpu_realtime_mask``,
   refer to :doc:`/configuration/extra-specs`

.. note::

   For more information about real-time functionality, refer to the
   :doc:`documentation <real-time>`.

It is also possible to configure the CPU policy via image metadata. This can
be useful when packaging applications that require real-time or near real-time
behavior by ensuring instances created with a given image are always pinned
regardless of flavor. To configure an image to use the ``dedicated`` CPU
policy, run:

.. code-block:: console

   $ openstack image set $IMAGE --property hw_cpu_policy=dedicated

Likewise, to configure an image to use the ``shared`` CPU policy, run:

.. code-block:: console

   $ openstack image set $IMAGE --property hw_cpu_policy=shared

.. note::

   For more information about image metadata, refer to the `Image metadata`_
   guide.

.. important::

   Flavor-based policies take precedence over image-based policies. For
   example, if a flavor specifies a CPU policy of ``dedicated`` then that
   policy will be used. If the flavor specifies a CPU policy of
   ``shared`` and the image specifies no policy or a policy of ``shared`` then
   the ``shared`` policy will be used. However, the flavor specifies a CPU
   policy of ``shared`` and the image specifies a policy of ``dedicated``, or
   vice versa, an exception will be raised. This is by design. Image metadata
   is often configurable by non-admin users, while flavors are only
   configurable by admins. By setting a ``shared`` policy through flavor
   extra-specs, administrators can prevent users configuring CPU policies in
   images and impacting resource utilization.

Customizing instance CPU thread pinning policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. important::

   The functionality described below requires the use of pinned instances and
   is therefore currently only supported by the libvirt/KVM driver and requires
   :ref:`some host configuration <configure-libvirt-pinning>` for this to work.

When running pinned instances on SMT hosts, it may also be necessary to
consider the impact that thread siblings can have on the instance workload. The
presence of an SMT implementation like Intel Hyper-Threading can boost
performance `by up to 30%`__ for some workloads.  However, thread siblings
share a number of components and contention on these components can diminish
performance for other workloads. For this reason, it is also possible to
explicitly request hosts with or without SMT.

__ https://software.intel.com/en-us/articles/how-to-determine-the-effectiveness-of-hyper-threading-technology-with-an-application

To configure whether an instance should be placed on a host with SMT or not, a
CPU thread policy may be specified. For workloads where sharing benefits
performance, you can request hosts **with** SMT.  To configure this, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=require

This will ensure the instance gets scheduled to a host with SMT by requesting
hosts that report the ``HW_CPU_HYPERTHREADING`` trait. It is also possible to
request this trait explicitly. To configure this, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property resources:PCPU=N \
     --property trait:HW_CPU_HYPERTHREADING=required

For other workloads where performance is impacted by contention for resources,
you can request hosts **without** SMT. To configure this, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=isolate

This will ensure the instance gets scheduled to a host without SMT by
requesting hosts that **do not** report the ``HW_CPU_HYPERTHREADING`` trait.
It is also possible to request this trait explicitly. To configure this, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property resources:PCPU=N \
     --property trait:HW_CPU_HYPERTHREADING=forbidden

Finally, for workloads where performance is minimally impacted, you may use
thread siblings if available and fallback to not using them if necessary. This
is the default, but it can be set explicitly:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=prefer

This does not utilize traits and, as such, there is no trait-based equivalent.

.. note::

   For more information about the syntax for ``hw:cpu_thread_policy``, refer to
   :doc:`/configuration/extra-specs`.

As with CPU policies, it also possible to configure the CPU thread policy via
image metadata. This can be useful when packaging applications that require
real-time or near real-time behavior by ensuring instances created with a given
image are always pinned regardless of flavor. To configure an image to use the
``require`` CPU policy, run:

.. code-block:: console

   $ openstack image set $IMAGE \
     --property hw_cpu_policy=dedicated \
     --property hw_cpu_thread_policy=require

Likewise, to configure an image to use the ``isolate`` CPU thread policy, run:

.. code-block:: console

   $ openstack image set $IMAGE \
     --property hw_cpu_policy=dedicated \
     --property hw_cpu_thread_policy=isolate

Finally, to configure an image to use the ``prefer`` CPU thread policy, run:

.. code-block:: console

   $ openstack image set $IMAGE \
     --property hw_cpu_policy=dedicated \
     --property hw_cpu_thread_policy=prefer

If the flavor does not specify a CPU thread policy then the CPU thread policy
specified by the image (if any) will be used. If both the flavor and image
specify a CPU thread policy then they must specify the same policy, otherwise
an exception will be raised.

.. note::

   For more information about image metadata, refer to the `Image metadata`_
   guide.

.. _emulator-thread-pinning-policies:

Customizing instance emulator thread pinning policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. important::

   The functionality described below requires the use of pinned instances and
   is therefore currently only supported by the libvirt/KVM driver and requires
   :ref:`some host configuration <configure-libvirt-pinning>` for this to work.

In addition to the work of the guest OS and applications running in an
instance, there is a small amount of overhead associated with the underlying
hypervisor. By default, these overhead tasks - known collectively as emulator
threads - run on the same host CPUs as the instance itself and will result in a
minor performance penalty for the instance. This is not usually an issue,
however, for things like real-time instances, it may not be acceptable for
emulator thread to steal time from instance CPUs.

Emulator thread policies can be used to ensure emulator threads are run on
cores separate from those used by the instance. There are two policies:
``isolate`` and ``share``. The default is to run the emulator threads on the
same core. The ``isolate`` emulator thread policy is used to specify that
emulator threads for a given instance should be run on their own unique core,
chosen from one of the host cores listed in
:oslo.config:option:`compute.cpu_dedicated_set`. To configure a flavor to use
the ``isolate`` emulator thread policy, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_policy=dedicated \
     --property hw:emulator_threads_policy=isolate

The ``share`` policy is used to specify that emulator threads from a given
instance should be run on the pool of host cores listed in
:oslo.config:option:`compute.cpu_shared_set` if configured, else across all
pCPUs of the instance.
To configure a flavor to use the ``share`` emulator thread policy, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_policy=dedicated \
     --property hw:emulator_threads_policy=share

The above behavior can be summarized in this helpful table:

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

.. note::

   For more information about the syntax for ``hw:emulator_threads_policy``,
   refer to :nova:extra-spec:`the documentation <hw:emulator_threads_policy>`.

Customizing instance CPU topologies
-----------------------------------

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver.

.. note::
   Currently it also works with libvirt/QEMU driver but we don't recommend
   it in production use cases. This is because vCPUs are actually running
   in one thread on host in qemu TCG (Tiny Code Generator), which is the
   backend for libvirt/QEMU driver. Work to enable full multi-threading
   support for TCG (a.k.a. MTTCG) is on going in QEMU community. Please see
   this `MTTCG project`_ page for detail.

In addition to configuring how an instance is scheduled on host CPUs, it is
possible to configure how CPUs are represented in the instance itself. By
default, when instance NUMA placement is not specified, a topology of N
sockets, each with one core and one thread, is used for an instance, where N
corresponds to the number of instance vCPUs requested. When instance NUMA
placement is specified, the number of sockets is fixed to the number of host
NUMA nodes to use and the total number of instance CPUs is split over these
sockets.

Some workloads benefit from a custom topology. For example, in some operating
systems, a different license may be needed depending on the number of CPU
sockets. To configure a flavor to use two sockets, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:cpu_sockets=2

Similarly, to configure a flavor to use one core and one thread, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_cores=1 \
     --property hw:cpu_threads=1

.. caution::

   If specifying all values, the product of sockets multiplied by cores
   multiplied by threads must equal the number of instance vCPUs. If specifying
   any one of these values or the multiple of two values, the values must be a
   factor of the number of instance vCPUs to prevent an exception. For example,
   specifying ``hw:cpu_sockets=2`` on a host with an odd number of cores fails.
   Similarly, specifying ``hw:cpu_cores=2`` and ``hw:cpu_threads=4`` on a host
   with ten cores fails.

For more information about the syntax for ``hw:cpu_sockets``, ``hw:cpu_cores``
and ``hw:cpu_threads``, refer to :doc:`/configuration/extra-specs`.

It is also possible to set upper limits on the number of sockets, cores, and
threads used. Unlike the hard values above, it is not necessary for this exact
number to used because it only provides a limit. This can be used to provide
some flexibility in scheduling, while ensuring certain limits are not
exceeded. For example, to ensure no more than two sockets, eight cores and one
thread are defined in the instance topology, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
     --property hw:cpu_max_sockets=2 \
     --property hw:cpu_max_cores=8 \
     --property hw:cpu_max_threads=1

For more information about the syntax for ``hw:cpu_max_sockets``,
``hw:cpu_max_cores``, and ``hw:cpu_max_threads``, refer to
:doc:`/configuration/extra-specs`.

Applications are frequently packaged as images. For applications that prefer
certain CPU topologies, configure image metadata to hint that created instances
should have a given topology regardless of flavor. To configure an image to
request a two-socket, four-core per socket topology, run:

.. code-block:: console

   $ openstack image set $IMAGE \
     --property hw_cpu_sockets=2 \
     --property hw_cpu_cores=4

To constrain instances to a given limit of sockets, cores or threads, use the
``max_`` variants. To configure an image to have a maximum of two sockets and a
maximum of one thread, run:

.. code-block:: console

   $ openstack image set $IMAGE \
     --property hw_cpu_max_sockets=2 \
     --property hw_cpu_max_threads=1

The value specified in the flavor is treated as the absolute limit.  The image
limits are not permitted to exceed the flavor limits, they can only be equal
to or lower than what the flavor defines. By setting a ``max`` value for
sockets, cores, or threads, administrators can prevent users configuring
topologies that might, for example, incur an additional licensing fees.

For more information about image metadata, refer to the `Image metadata`_
guide.

.. _configure-libvirt-pinning:

Configuring libvirt compute nodes for CPU pinning
-------------------------------------------------

.. versionchanged:: 20.0.0

   Prior to 20.0.0 (Train), it was not necessary to explicitly configure hosts
   for pinned instances. However, it was not possible to place pinned instances
   on the same host as unpinned CPUs, which typically meant hosts had to be
   grouped into host aggregates. If this was not done, unpinned instances would
   continue floating across all enabled host CPUs, even those that some
   instance CPUs were pinned to. Starting in 20.0.0, it is necessary to
   explicitly identify the host cores that should be used for pinned instances.

Nova treats host CPUs used for unpinned instances differently from those used
by pinned instances. The former are tracked in placement using the ``VCPU``
resource type and can be overallocated, while the latter are tracked using the
``PCPU`` resource type. By default, nova will report all host CPUs as ``VCPU``
inventory, however, this can be configured using the
:oslo.config:option:`compute.cpu_shared_set` config option, to specify which
host CPUs should be used for ``VCPU`` inventory, and the
:oslo.config:option:`compute.cpu_dedicated_set` config option, to specify which
host CPUs should be used for ``PCPU`` inventory.

Consider a compute node with a total of 24 host physical CPU cores with
hyperthreading enabled. The operator wishes to reserve 1 physical CPU core and
its thread sibling for host processing (not for guest instance use).
Furthermore, the operator wishes to use 8 host physical CPU cores and their
thread siblings for dedicated guest CPU resources. The remaining 15 host
physical CPU cores and their thread siblings will be used for shared guest vCPU
usage, with an 8:1 allocation ratio for those physical processors used for
shared guest CPU resources.

The operator could configure ``nova.conf`` like so::

    [DEFAULT]
    cpu_allocation_ratio=8.0

    [compute]
    cpu_dedicated_set=2-17
    cpu_shared_set=18-47

The virt driver will construct a provider tree containing a single resource
provider representing the compute node and report inventory of ``PCPU`` and
``VCPU`` for this single provider accordingly::

    COMPUTE NODE provider
        PCPU:
            total: 16
            reserved: 0
            min_unit: 1
            max_unit: 16
            step_size: 1
            allocation_ratio: 1.0
        VCPU:
            total: 30
            reserved: 0
            min_unit: 1
            max_unit: 30
            step_size: 1
            allocation_ratio: 8.0

Instances using the ``dedicated`` CPU policy or an explicit ``PCPU`` resource
request, ``PCPU`` inventory will be consumed. Instances using the ``shared``
CPU policy, meanwhile, will consume ``VCPU`` inventory.

.. note::

   ``PCPU`` and ``VCPU`` allocations are currently combined to calculate the
   value for the ``cores`` quota class.

.. _configure-hyperv-numa:

Configuring CPU power management for dedicated cores
----------------------------------------------------

.. versionchanged:: 27.0.0

   This feature was only introduced by the 2023.1 Antelope release

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver.

For power saving reasons, operators can decide to turn down the power usage of
CPU cores whether they are in use or not. For obvious reasons, Nova only allows
to change the power consumption of a dedicated CPU core and not a shared one.
Accordingly, usage of this feature relies on the reading of
:oslo.config:option:`compute.cpu_dedicated_set` config option to know which CPU
cores to handle.
The main action to enable the power management of dedicated cores is to set
:oslo.config:option:`libvirt.cpu_power_management` config option to ``True``.

By default, if this option is enabled, Nova will lookup the dedicated cores and
power them down at the compute service startup. Then, once an instance starts
by being attached to a dedicated core, this below core will be powered up right
before the libvirt guest starts. On the other way, once an instance is stopped,
migrated or deleted, then the corresponding dedicated core will be powered down.

There are two distinct strategies for powering up or down :

- the default is to offline the CPU core and online it when needed.
- an alternative strategy is to use two distinct CPU governors for the up state
  and the down state.

The strategy can be chosen using
:oslo.config:option:`libvirt.cpu_power_management_strategy` config option.
``cpu_state`` supports the first online/offline strategy, while ``governor``
sets the alternative strategy.
We default to turning off the cores as it provides you the best power savings
while there could be other tools outside Nova to manage the governor, like
tuned. That being said, we also provide a way to automatically change the
governors on the fly, as explained below.

.. important::
   Some OS platforms don't support ``cpufreq`` resources in sysfs, so the
   ``governor`` strategy could be not available. Please verify if your OS
   supports scaling govenors before modifying the configuration option.

If the strategy is set to ``governor``, a couple of config options are provided
to define which exact CPU governor to use for each of the up and down states :

- :oslo.config:option:`libvirt.cpu_power_governor_low` will define the governor
  to use for the powerdown state (defaults to ``powersave``)
- :oslo.config:option:`libvirt.cpu_power_governor_high` will define the
  governor to use for the powerup state (defaults to ``performance``)

.. important::
   This is the responsibility of the operator to ensure that the govenors
   defined by the configuration options are currently supported by the OS
   underlying kernel that runs the compute service.

   As a side note, we recommend the ``schedutil`` governor as an alternative for
   the high-power state (if the kernel supports it) as the CPU frequency is
   dynamically set based on CPU task states. Other governors may be worth to
   be tested, including ``conservative`` and ``ondemand`` which are quite a bit
   more power consuming than ``schedutil`` but more efficient than
   ``performance``. See `Linux kernel docs`_ for further explanations.

.. _`Linux kernel docs`: https://www.kernel.org/doc/Documentation/cpu-freq/governors.txt

As an example, a ``nova.conf`` part of configuration would look like::

    [compute]
    cpu_dedicated_set=2-17

    [libvirt]
    cpu_power_management=True
    cpu_power_management_strategy=cpu_state

.. warning::

   The CPU core #0 has a special meaning in most of the recent Linux kernels.
   This is always highly discouraged to use it for CPU pinning but please
   refrain to have it power managed or you could have surprises if Nova turns
   it off!

One last important note : you can decide to change the CPU management strategy
during the compute lifecycle, or you can currently already manage the CPU
states. For ensuring that Nova can correctly manage the CPU performances, we
added a couple of checks at startup that refuse to start nova-compute service
if those arbitrary rules aren't enforced :

- if the operator opts for ``cpu_state`` strategy, then all dedicated CPU
  governors *MUST* be identical.
- if they decide using ``governor``, then all dedicated CPU cores *MUST* be
  online.

.. Links
.. _`Image metadata`: https://docs.openstack.org/image-guide/introduction.html#image-metadata
.. _`MTTCG project`: http://wiki.qemu.org/Features/tcg-multithread
