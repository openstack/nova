==========
Huge pages
==========

The huge page feature in OpenStack provides important performance improvements
for applications that are highly memory IO-bound.

.. note::

   Huge pages may also be referred to hugepages or large pages, depending on
   the source. These terms are synonyms.

Pages, the TLB and huge pages
-----------------------------

Pages
  Physical memory is segmented into a series of contiguous regions called
  pages. Each page contains a number of bytes, referred to as the page size.
  The system retrieves memory by accessing entire pages, rather than byte by
  byte.

Translation Lookaside Buffer (TLB)
  A TLB is used to map the virtual addresses of pages to the physical addresses
  in actual memory. The TLB is a cache and is not limitless, storing only the
  most recent or frequently accessed pages. During normal operation, processes
  will sometimes attempt to retrieve pages that are not stored in the cache.
  This is known as a TLB miss and results in a delay as the processor iterates
  through the pages themselves to find the missing address mapping.

Huge Pages
  The standard page size in x86 systems is 4 kB. This is optimal for general
  purpose computing but larger page sizes - 2 MB and 1 GB - are also available.
  These larger page sizes are known as huge pages. Huge pages result in less
  efficient memory usage as a process will not generally use all memory
  available in each page. However, use of huge pages will result in fewer
  overall pages and a reduced risk of TLB misses. For processes that have
  significant memory requirements or are memory intensive, the benefits of huge
  pages frequently outweigh the drawbacks.

Persistent Huge Pages
  On Linux hosts, persistent huge pages are huge pages that are reserved
  upfront. The HugeTLB provides for the mechanism for this upfront
  configuration of huge pages. The HugeTLB allows for the allocation of varying
  quantities of different huge page sizes. Allocation can be made at boot time
  or run time. Refer to the `Linux hugetlbfs guide`_ for more information.

Transparent Huge Pages (THP)
  On Linux hosts, transparent huge pages are huge pages that are automatically
  provisioned based on process requests. Transparent huge pages are provisioned
  on a best effort basis, attempting to provision 2 MB huge pages if available
  but falling back to 4 kB small pages if not. However, no upfront
  configuration is necessary. Refer to the `Linux THP guide`_ for more
  information.

Enabling huge pages on the host
-------------------------------

.. important::
   Huge pages may not be used on a host configured for file-backed memory. See
   :doc:`file-backed-memory` for details

Persistent huge pages are required owing to their guaranteed availability.
However, persistent huge pages are not enabled by default in most environments.
The steps for enabling huge pages differ from platform to platform and only the
steps for Linux hosts are described here. On Linux hosts, the number of
persistent huge pages on the host can be queried by checking ``/proc/meminfo``:

.. code-block:: console

   $ grep Huge /proc/meminfo
   AnonHugePages:         0 kB
   ShmemHugePages:        0 kB
   HugePages_Total:       0
   HugePages_Free:        0
   HugePages_Rsvd:        0
   HugePages_Surp:        0
   Hugepagesize:       2048 kB

In this instance, there are 0 persistent huge pages (``HugePages_Total``) and 0
transparent huge pages (``AnonHugePages``) allocated. Huge pages can be
allocated at boot time or run time. Huge pages require a contiguous area of
memory - memory that gets increasingly fragmented the long a host is running.
Identifying contiguous areas of memory is an issue for all huge page sizes, but
it is particularly problematic for larger huge page sizes such as 1 GB huge
pages. Allocating huge pages at boot time will ensure the correct number of huge
pages is always available, while allocating them at run time can fail if memory
has become too fragmented.

To allocate huge pages at run time, the kernel boot parameters must be extended
to include some huge page-specific parameters. This can be achieved by
modifying ``/etc/default/grub`` and appending the ``hugepagesz``,
``hugepages``, and ``transparent_hugepages=never`` arguments to
``GRUB_CMDLINE_LINUX``. To allocate, for example, 2048 persistent 2 MB huge
pages at boot time, run:

.. code-block:: console

   # echo 'GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX hugepagesz=2M hugepages=2048 transparent_hugepage=never"' > /etc/default/grub
   $ grep GRUB_CMDLINE_LINUX /etc/default/grub
   GRUB_CMDLINE_LINUX="..."
   GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX hugepagesz=2M hugepages=2048 transparent_hugepage=never"

.. important::

   Persistent huge pages are not usable by standard host OS processes. Ensure
   enough free, non-huge page memory is reserved for these processes.

Reboot the host, then validate that huge pages are now available:

.. code-block:: console

   $ grep "Huge" /proc/meminfo
   AnonHugePages:         0 kB
   ShmemHugePages:        0 kB
   HugePages_Total:    2048
   HugePages_Free:     2048
   HugePages_Rsvd:        0
   HugePages_Surp:        0
   Hugepagesize:       2048 kB

There are now 2048 2 MB huge pages totalling 4 GB of huge pages. These huge
pages must be mounted. On most platforms, this happens automatically. To verify
that the huge pages are mounted, run:

.. code-block:: console

   # mount | grep huge
   hugetlbfs on /dev/hugepages type hugetlbfs (rw)

In this instance, the huge pages are mounted at ``/dev/hugepages``. This mount
point varies from platform to platform. If the above command did not return
anything, the hugepages must be mounted manually. To mount the huge pages at
``/dev/hugepages``, run:

.. code-block:: console

   # mkdir -p /dev/hugepages
   # mount -t hugetlbfs hugetlbfs /dev/hugepages

There are many more ways to configure huge pages, including allocating huge
pages at run time, specifying varying allocations for different huge page
sizes, or allocating huge pages from memory affinitized to different NUMA
nodes. For more information on configuring huge pages on Linux hosts, refer to
the `Linux hugetlbfs guide`_.

Customizing instance huge pages allocations
-------------------------------------------

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver.

.. important::

   For performance reasons, configuring huge pages for an instance will
   implicitly result in a NUMA topology being configured for the instance.
   Configuring a NUMA topology for an instance requires enablement of
   ``NUMATopologyFilter``. Refer to :doc:`cpu-topologies` for more
   information.

By default, an instance does not use huge pages for its underlying memory.
However, huge pages can bring important or required performance improvements
for some workloads. Huge pages must be requested explicitly through the use of
flavor extra specs or image metadata. To request an instance use huge pages,
run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=large

Different platforms offer different huge page sizes. For example: x86-based
platforms offer 2 MB and 1 GB huge page sizes. Specific huge page sizes can be
also be requested, with or without a unit suffix. The unit suffix must be one
of: Kb(it), Kib(it), Mb(it), Mib(it), Gb(it), Gib(it), Tb(it), Tib(it), KB,
KiB, MB, MiB, GB, GiB, TB, TiB. Where a unit suffix is not provided, Kilobytes
are assumed. To request an instance to use 2 MB huge pages, run one of:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=2MB

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=2048

Enabling huge pages for an instance can have negative consequences for other
instances by consuming limited huge pages resources. To explicitly request
an instance use small pages, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=small

.. note::

   Explicitly requesting any page size will still result in a NUMA topology
   being applied to the instance, as described earlier in this document.

Finally, to leave the decision of huge or small pages to the compute driver,
run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=any

For more information about the syntax for ``hw:mem_page_size``, refer to
:doc:`flavors`.

Applications are frequently packaged as images. For applications that require
the IO performance improvements that huge pages provides, configure image
metadata to ensure instances always request the specific page size regardless
of flavor. To configure an image to use 1 GB huge pages, run:

.. code-block:: console

   $ openstack image set [IMAGE_ID]  --property hw_mem_page_size=1GB

If the flavor specifies a numerical page size or a page size of "small" the
image is not allowed to specify a page size and if it does an exception will
be raised. If the flavor specifies a page size of ``any`` or ``large`` then
any page size specified in the image will be used. By setting a ``small``
page size in the flavor, administrators can prevent users requesting huge
pages in flavors and impacting resource utilization. To configure this page
size, run:

.. code-block:: console

   $ openstack flavor set m1.large --property hw:mem_page_size=small

.. note::

   Explicitly requesting any page size will still result in a NUMA topology
   being applied to the instance, as described earlier in this document.

For more information about image metadata, refer to the `Image metadata`_
guide.

.. Links
.. _`Linux THP guide`: https://www.kernel.org/doc/Documentation/vm/transhuge.txt
.. _`Linux hugetlbfs guide`: https://www.kernel.org/doc/Documentation/vm/hugetlbpage.txt
.. _`Image metadata`: https://docs.openstack.org/image-guide/introduction.html#image-metadata
