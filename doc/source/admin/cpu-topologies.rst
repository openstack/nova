==============
CPU topologies
==============

The NUMA topology and CPU pinning features in OpenStack provide high-level
control over how instances run on hypervisor CPUs and the topology of virtual
CPUs available to instances. These features help minimize latency and maximize
performance.

SMP, NUMA, and SMT
~~~~~~~~~~~~~~~~~~

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

In OpenStack, SMP CPUs are known as *cores*, NUMA cells or nodes are known as
*sockets*, and SMT CPUs are known as *threads*. For example, a quad-socket,
eight core system with Hyper-Threading would have four sockets, eight cores per
socket and two threads per core, for a total of 64 CPUs.

Configuring compute nodes for instances with NUMA placement policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Hyper-V is configured by default to allow instances to span multiple NUMA
nodes, regardless if the instances have been configured to only span N NUMA
nodes. This behaviour allows Hyper-V instances to have up to 64 vCPUs and 1 TB
of memory.

Checking NUMA spanning can easily be done by running this following powershell
command:

.. code-block:: console

   (Get-VMHost).NumaSpanningEnabled

In order to disable this behaviour, the host will have to be configured to
disable NUMA spanning. This can be done by executing these following
powershell commands:

.. code-block:: console

   Set-VMHost -NumaSpanningEnabled $false
   Restart-Service vmms

In order to restore this behaviour, execute these powershell commands:

.. code-block:: console

   Set-VMHost -NumaSpanningEnabled $true
   Restart-Service vmms

The ``vmms`` service (Virtual Machine Management Service) is responsible for
managing the Hyper-V VMs. The VMs will still run while the service is down
or restarting, but they will not be manageable by the ``nova-compute``
service. In order for the effects of the Host NUMA spanning configuration
to take effect, the VMs will have to be restarted.

Hyper-V does not allow instances with a NUMA topology to have dynamic
memory allocation turned on. The Hyper-V driver will ignore the configured
``dynamic_memory_ratio`` from the given ``nova.conf`` file when spawning
instances with a NUMA topology.

Customizing instance NUMA placement policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM and Hyper-V driver.

When running workloads on NUMA hosts, it is important that the vCPUs executing
processes are on the same NUMA node as the memory used by these processes.
This ensures all memory accesses are local to the node and thus do not consume
the limited cross-node memory bandwidth, adding latency to memory accesses.
Similarly, large pages are assigned from memory and benefit from the same
performance improvements as memory allocated using standard pages. Thus, they
also should be local. Finally, PCI devices are directly associated with
specific NUMA nodes for the purposes of DMA. Instances that use PCI or SR-IOV
devices should be placed on the NUMA node associated with these devices.

By default, an instance floats across all NUMA nodes on a host. NUMA awareness
can be enabled implicitly through the use of huge pages or pinned CPUs or
explicitly through the use of flavor extra specs or image metadata.  In all
cases, the ``NUMATopologyFilter`` filter must be enabled. Details on this
filter are provided in :doc:`/admin/configuration/schedulers` in Nova
configuration guide.

.. caution::

   The NUMA node(s) used are normally chosen at random. However, if a PCI
   passthrough or SR-IOV device is attached to the instance, then the NUMA
   node that the device is associated with will be used. This can provide
   important performance improvements. However, booting a large number of
   similar instances can result in unbalanced NUMA node usage. Care should
   be taken to mitigate this issue. See this `discussion`_ for more details.

.. caution::

   Inadequate per-node resources will result in scheduling failures. Resources
   that are specific to a node include not only CPUs and memory, but also PCI
   and SR-IOV resources. It is not possible to use multiple resources from
   different nodes without requesting a multi-node layout. As such, it may be
   necessary to ensure PCI or SR-IOV resources are associated with the same
   NUMA node or force a multi-node layout.

When used, NUMA awareness allows the operating system of the instance to
intelligently schedule the workloads that it runs and minimize cross-node
memory bandwidth. To restrict an instance's vCPUs to a single host NUMA node,
run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:numa_nodes=1

Some workloads have very demanding requirements for memory access latency or
bandwidth that exceed the memory bandwidth available from a single NUMA node.
For such workloads, it is beneficial to spread the instance across multiple
host NUMA nodes, even if the instance's RAM/vCPUs could theoretically fit on a
single NUMA node. To force an instance's vCPUs to spread across two host NUMA
nodes, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:numa_nodes=2

The allocation of instances vCPUs and memory from different host NUMA nodes can
be configured. This allows for asymmetric allocation of vCPUs and memory, which
can be important for some workloads. To spread the 6 vCPUs and 6 GB of memory
of an instance across two NUMA nodes and create an asymmetric 1:2 vCPU and
memory mapping between the two nodes, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:numa_nodes=2
   $ openstack flavor set m1.large \  # configure guest node 0
     --property hw:numa_cpus.0=0,1 \
     --property hw:numa_mem.0=2048
   $ openstack flavor set m1.large \  # configure guest node 1
     --property hw:numa_cpus.1=2,3,4,5 \
     --property hw:numa_mem.1=4096

.. note::

    Hyper-V does not support asymmetric NUMA topologies, and the Hyper-V
    driver will not spawn instances with such topologies.

For more information about the syntax for ``hw:numa_nodes``, ``hw:numa_cpus.N``
and ``hw:num_mem.N``, refer to the :ref:`NUMA
topology <extra-specs-numa-topology>` guide.

Customizing instance CPU pinning policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver. Hyper-V does not support CPU pinning.

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
contention between instances. To configure a flavor to use pinned vCPUs, a
use a dedicated CPU policy. To force this, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:cpu_policy=dedicated

.. caution::

   Host aggregates should be used to separate pinned instances from unpinned
   instances as the latter will not respect the resourcing requirements of
   the former.

When running workloads on SMT hosts, it is important to be aware of the impact
that thread siblings can have. Thread siblings share a number of components
and contention on these components can impact performance. To configure how
to use threads, a CPU thread policy should be specified. For workloads where
sharing benefits performance, use thread siblings. To force this, run:

.. code-block:: console

   $ openstack flavor set m1.large \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=require

For other workloads where performance is impacted by contention for resources,
use non-thread siblings or non-SMT hosts. To force this, run:

.. code-block:: console

   $ openstack flavor set m1.large \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=isolate

Finally, for workloads where performance is minimally impacted, use thread
siblings if available. This is the default, but it can be set explicitly:

.. code-block:: console

   $ openstack flavor set m1.large \
     --property hw:cpu_policy=dedicated \
     --property hw:cpu_thread_policy=prefer

For more information about the syntax for ``hw:cpu_policy`` and
``hw:cpu_thread_policy``, refer to the :doc:`/admin/flavors` guide.

Applications are frequently packaged as images. For applications that require
real-time or near real-time behavior, configure image metadata to ensure
created instances are always pinned regardless of flavor. To configure an
image to use pinned vCPUs and avoid thread siblings, run:

.. code-block:: console

   $ openstack image set [IMAGE_ID] \
     --property hw_cpu_policy=dedicated \
     --property hw_cpu_thread_policy=isolate

If the flavor specifies a CPU policy of ``dedicated`` then that policy will be
used. If the flavor explicitly specifies a CPU policy of ``shared`` and the
image specifies no policy or a policy of ``shared`` then the ``shared`` policy
will be used, but if the image specifies a policy of ``dedicated`` an exception
will be raised. By setting a ``shared`` policy through flavor extra-specs,
administrators can prevent users configuring CPU policies in images and
impacting resource utilization. To configure this policy, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:cpu_policy=shared

If the flavor does not specify a CPU thread policy then the CPU thread policy
specified by the image (if any) will be used. If both the flavor and image
specify a CPU thread policy then they must specify the same policy, otherwise
an exception will be raised.

.. note::

   There is no correlation required between the NUMA topology exposed in the
   instance and how the instance is actually pinned on the host. This is by
   design. See this `invalid bug
   <https://bugs.launchpad.net/nova/+bug/1466780>`_ for more information.

For more information about image metadata, refer to the `Image metadata`_
guide.

Customizing instance CPU topologies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
sockets. To configure a flavor to use a maximum of two sockets, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:cpu_sockets=2

Similarly, to configure a flavor to use one core and one thread, run:

.. code-block:: console

   $ openstack flavor set m1.large \
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
and ``hw:cpu_threads``, refer to the :doc:`/admin/flavors` guide.

It is also possible to set upper limits on the number of sockets, cores, and
threads used. Unlike the hard values above, it is not necessary for this exact
number to used because it only provides a limit. This can be used to provide
some flexibility in scheduling, while ensuring certain limits are not
exceeded. For example, to ensure no more than two sockets are defined in the
instance topology, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:cpu_max_sockets=2

For more information about the syntax for ``hw:cpu_max_sockets``,
``hw:cpu_max_cores``, and ``hw:cpu_max_threads``, refer to the
:doc:`/admin/flavors` guide.

Applications are frequently packaged as images. For applications that prefer
certain CPU topologies, configure image metadata to hint that created instances
should have a given topology regardless of flavor. To configure an image to
request a two-socket, four-core per socket topology, run:

.. code-block:: console

   $ openstack image set [IMAGE_ID] \
     --property hw_cpu_sockets=2 \
     --property hw_cpu_cores=4

To constrain instances to a given limit of sockets, cores or threads, use the
``max_`` variants. To configure an image to have a maximum of two sockets and a
maximum of one thread, run:

.. code-block:: console

   $ openstack image set [IMAGE_ID] \
     --property hw_cpu_max_sockets=2 \
     --property hw_cpu_max_threads=1

The value specified in the flavor is treated as the absolute limit.  The image
limits are not permitted to exceed the flavor limits, they can only be equal
to or lower than what the flavor defines. By setting a ``max`` value for
sockets, cores, or threads, administrators can prevent users configuring
topologies that might, for example, incur an additional licensing fees.

For more information about image metadata, refer to the `Image metadata`_
guide.

.. Links
.. _`Image metadata`: https://docs.openstack.org/image-guide/image-metadata.html
.. _`discussion`: http://lists.openstack.org/pipermail/openstack-dev/2016-March/090367.html
.. _`MTTCG project`: http://wiki.qemu.org/Features/tcg-multithread
