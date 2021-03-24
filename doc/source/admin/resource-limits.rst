===============
Resource Limits
===============

Nova supports configuring limits on individual resources including CPU, memory,
disk and network. These limits can be used to enforce basic Quality-of-Service
(QoS) policies on such resources.

.. note::

   Hypervisor-enforced resource limits are distinct from API-enforced user and
   project quotas. For information on the latter, refer to :doc:`quotas`.

.. warning::

   This feature is poorly tested and poorly maintained. It may no longer work
   as expected. Where possible, consider using the QoS policies provided by
   other services, such as
   :cinder-doc:`Cinder </admin/blockstorage-basic-volume-qos.html>` and
   :neutron-doc:`Neutron </admin/config-qos.html>`.


Configuring resource limits
---------------------------

Resource quota enforcement support is specific to the virt driver in use on
compute hosts.

libvirt
~~~~~~~

The libvirt driver supports CPU, disk and VIF limits. Unfortunately all of
these work quite differently, as discussed below.

CPU limits
^^^^^^^^^^

Libvirt enforces CPU limits in terms of *shares* and *quotas*, configured
via :nova:extra-spec:`quota:cpu_shares` and :nova:extra-spec:`quota:cpu_period`
/ :nova:extra-spec:`quota:cpu_quota`, respectively. Both are implemented using
the `cgroups v1 cpu controller`__.

CPU shares are a proportional weighted share of total CPU resources relative to
other instances. It does not limit CPU usage if CPUs are not busy. There is no
unit and the value is purely relative to other instances, so an instance
configured with value of 2048 will get twice as much CPU time as a VM
configured with the value 1024. For example, to configure a CPU share of 1024
for a flavor:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property quota:cpu_shares=1024

The CPU quotas require both a period and quota. The CPU period specifies the
enforcement interval in microseconds, while the CPU quota specifies the maximum
allowed bandwidth in microseconds that the each vCPU of the instance can
consume. The CPU period must be in the range 1000 (1mS) to 1,000,000 (1s) or 0
(disabled). The CPU quota must be in the range 1000 (1mS) to 2^64 or 0
(disabled). Where the CPU quota exceeds the CPU period, this means the guest
vCPU process is able to consume multiple pCPUs worth of bandwidth. For example,
to limit each guest vCPU to 1 pCPU worth of runtime per period:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:cpu_period=1000 \
       --property quota:cpu_quota=1000

To limit each guest vCPU to 2 pCPUs worth of runtime per period:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:cpu_period=1000 \
       --property quota:cpu_quota=2000

Finally, to limit each guest vCPU to 0.5 pCPUs worth of runtime per period:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:cpu_period=1000 \
       --property quota:cpu_quota=500

.. note::

   Smaller periods will ensure a consistent latency response at the expense of
   burst capacity.

CPU shares and CPU quotas can work hand-in-hand. For example, if two instances
were configured with :nova:extra-spec:`quota:cpu_shares`\ =1024 and
:nova:extra-spec:`quota:cpu_period`\ =100000 (100mS) for both, then configuring
both with a :nova:extra-spec:`quota:cpu_quota`\ =75000 (75mS) will result in
them sharing a host CPU equally, with both getting exactly 50mS of CPU time.
If instead only one instance gets :nova:extra-spec:`quota:cpu_quota`\ =75000
(75mS) while the other gets :nova:extra-spec:`quota:cpu_quota`\ =25000 (25mS),
then the first will get 3/4 of the time per period.

.. __: https://man7.org/linux/man-pages/man7/cgroups.7.html

Memory Limits
^^^^^^^^^^^^^

The libvirt driver does not support memory limits.

Disk I/O Limits
^^^^^^^^^^^^^^^

Libvirt enforces disk limits through maximum disk read, write and total bytes
per second, using the :nova:extra-spec:`quota:disk_read_bytes_sec`,
:nova:extra-spec:`quota:disk_write_bytes_sec` and
:nova:extra-spec:`quota:disk_total_bytes_sec` extra specs, respectively. It can
also enforce disk limits through maximum disk read, write and total I/O
operations per second, using the :nova:extra-spec:`quota:disk_read_iops_sec`,
:nova:extra-spec:`quota:disk_write_iops_sec` and
:nova:extra-spec:`quota:disk_total_iops_sec` extra specs, respectively. For
example, to set a maximum disk write of 10 MB/sec for a flavor:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:disk_write_bytes_sec=10485760

Network bandwidth limits
^^^^^^^^^^^^^^^^^^^^^^^^

.. warning::

   These limits are enforced via libvirt and will only work where the network
   is connect to the instance using a tap interface. It will not work for
   things like :doc:`SR-IOV VFs <pci-passthrough>`.
   :neutron-doc:`Neutron's QoS policies </admin/config-qos.html>` should be
   preferred wherever possible.

Libvirt enforces network bandwidth limits through inbound and outbound average,
using the :nova:extra-spec:`quota:vif_inbound_average` and
:nova:extra-spec:`quota:vif_outbound_average` extra specs, respectively.
In addition, optional *peak* values, which specifies the maximum rate at which
a bridge can send data (kB/s), and *burst* values, which specifies the amount
of bytes that can be burst at peak speed (kilobytes), can be specified for both
inbound and outbound traffic, using the
:nova:extra-spec:`quota:vif_inbound_peak` /
:nova:extra-spec:`quota:vif_outbound_peak` and
:nova:extra-spec:`quota:vif_inbound_burst` /
:nova:extra-spec:`quota:vif_outbound_burst` extra specs, respectively.

For example, to configure **outbound** traffic to an average of 262 Mbit/s
(32768 kB/s), a peak of 524 Mbit/s, and burst of 65536 kilobytes:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:vif_outbound_average=32768 \
       --property quota:vif_outbound_peak=65536 \
       --property quota:vif_outbound_burst=65536

.. note::

   The speed limit values in above example are specified in kilobytes/second,
   whle the burst value is in kilobytes.

VMWare
~~~~~~

In contrast to libvirt, the VMWare virt driver enforces resource limits using
consistent terminology, specifically through relative allocation levels, hard
upper limits and minimum reservations configured via, for example, the
:nova:extra-spec:`quota:cpu_shares_level` /
:nova:extra-spec:`quota:cpu_shares_share`, :nova:extra-spec:`quota:cpu_limit`,
and :nova:extra-spec:`quota:cpu_reservation` extra specs, respectively.

Allocation levels can be specified using one of ``high``, ``normal``, ``low``,
or ``custom``. When ``custom`` is specified, the number of shares must be
specified using e.g. :nova:extra-spec:`quota:cpu_shares_share`. There is no
unit and the values are relative to other instances on the host. The upper
limits and reservations, by comparison, are measure in resource-specific units,
such as MHz for CPUs and will ensure that the instance never used more than or
gets less than the specified amount of the resource.

CPU limits
^^^^^^^^^^

CPU limits are configured via the :nova:extra-spec:`quota:cpu_shares_level` /
:nova:extra-spec:`quota:cpu_shares_share`, :nova:extra-spec:`quota:cpu_limit`,
and :nova:extra-spec:`quota:cpu_reservation` extra specs.

For example, to configure a CPU allocation level of ``custom`` with 1024
shares:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:cpu_shares_level=custom \
       --quota:cpu_shares_share=1024

To configure a minimum CPU allocation of 1024 MHz and a maximum of 2048 MHz:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:cpu_reservation=1024 \
       --quota:cpu_limit=2048

Memory limits
^^^^^^^^^^^^^

Memory limits are configured via the
:nova:extra-spec:`quota:memory_shares_level` /
:nova:extra-spec:`quota:memory_shares_share`,
:nova:extra-spec:`quota:memory_limit`, and
:nova:extra-spec:`quota:memory_reservation` extra specs.

For example, to configure a memory allocation level of ``custom`` with 1024
shares:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:memory_shares_level=custom \
       --quota:memory_shares_share=1024

To configure a minimum memory allocation of 1024 MB and a maximum of 2048 MB:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:memory_reservation=1024 \
       --quota:memory_limit=2048

Disk I/O limits
^^^^^^^^^^^^^^^

Disk I/O limits are configured via the
:nova:extra-spec:`quota:disk_io_shares_level` /
:nova:extra-spec:`quota:disk_io_shares_share`,
:nova:extra-spec:`quota:disk_io_limit`, and
:nova:extra-spec:`quota:disk_io_reservation` extra specs.

For example, to configure a disk I/O allocation level of ``custom`` with 1024
shares:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:disk_io_shares_level=custom \
       --quota:disk_io_shares_share=1024

To configure a minimum disk I/O allocation of 1024 MB and a maximum of 2048 MB:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:disk_io_reservation=1024 \
       --quota:disk_io_limit=2048

Network bandwidth limits
^^^^^^^^^^^^^^^^^^^^^^^^

Network bandwidth limits are configured via the
:nova:extra-spec:`quota:vif_shares_level` /
:nova:extra-spec:`quota:vif_shares_share`,
:nova:extra-spec:`quota:vif_limit`, and
:nova:extra-spec:`quota:vif_reservation` extra specs.

For example, to configure a network bandwidth allocation level of ``custom``
with 1024 shares:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:vif_shares_level=custom \
       --quota:vif_shares_share=1024

To configure a minimum bandwidth allocation of 1024 Mbits/sec and a maximum of
2048 Mbits/sec:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --quota:vif_reservation=1024 \
       --quota:vif_limit=2048

Hyper-V
~~~~~~~

CPU limits
^^^^^^^^^^

The Hyper-V driver does not support CPU limits.

Memory limits
^^^^^^^^^^^^^

The Hyper-V driver does not support memory limits.

Disk I/O limits
^^^^^^^^^^^^^^^

Hyper-V enforces disk limits through maximum total bytes and total I/O
operations per second, using the :nova:extra-spec:`quota:disk_total_bytes_sec`
and :nova:extra-spec:`quota:disk_total_iops_sec` extra specs, respectively. For
example, to set a maximum disk read/write of 10 MB/sec for a flavor:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property quota:disk_total_bytes_sec=10485760

Network bandwidth limits
^^^^^^^^^^^^^^^^^^^^^^^^

The Hyper-V driver does not support network bandwidth limits.
