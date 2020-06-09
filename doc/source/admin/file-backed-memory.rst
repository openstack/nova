==================
File-backed memory
==================

.. important::

   As of the 18.0.0 Rocky release, the functionality described below is
   only supported by the libvirt/KVM driver.

The file-backed memory feature in Openstack allows a Nova node to serve guest
memory from a file backing store. This mechanism uses the libvirt file memory
source, causing guest instance memory to be allocated as files within the
libvirt memory backing directory.

Since instance performance will be related to the speed of the backing store,
this feature works best when used with very fast block devices or virtual file
systems - such as flash or RAM devices.

When configured, ``nova-compute`` will report the capacity configured for
file-backed memory to placement in place of the total system memory capacity.
This allows the node to run more instances than would normally fit
within system memory.

When available in libvirt and qemu, instance memory will be discarded by qemu
at shutdown by calling ``madvise(MADV_REMOVE)``, to avoid flushing any dirty
memory to the backing store on exit.

To enable file-backed memory, follow the steps below:

#. `Configure the backing store`_

#. `Configure Nova Compute for file-backed memory`_

.. important::

   It is not possible to live migrate from a node running a version of
   OpenStack that does not support file-backed memory to a node with file
   backed memory enabled. It is recommended that all Nova compute nodes are
   upgraded to Rocky before enabling file-backed memory.

Prerequisites and Limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Libvirt
   File-backed memory requires libvirt version 4.0.0 or newer. Discard
   capability requires libvirt version 4.4.0 or newer.

Qemu
   File-backed memory requires qemu version 2.6.0 or newer. Discard capability
   requires qemu version 2.10.0 or newer.

Memory overcommit
   File-backed memory is not compatible with memory overcommit.
   :oslo.config:option:`ram_allocation_ratio` must be set to ``1.0`` in
   ``nova.conf``, and the host must not be added to a :doc:`host aggregate
   </admin/aggregates>` with ``ram_allocation_ratio`` set to anything but
   ``1.0``.

Reserved memory
   When configured, file-backed memory is reported as total system memory to
   placement, with RAM used as cache. Reserved memory corresponds to disk
   space not set aside for file-backed memory.
   :oslo.config:option:`reserved_host_memory_mb` should be set to ``0`` in
   ``nova.conf``.

Huge pages
   File-backed memory is not compatible with huge pages. Instances with huge
   pages configured will not start on a host with file-backed memory enabled. It
   is recommended to use host aggregates to ensure instances configured for
   huge pages are not placed on hosts with file-backed memory configured.

Handling these limitations could be optimized with a scheduler filter in the
future.

Configure the backing store
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

   ``/dev/sdb`` and the ``ext4`` filesystem are used here as an example. This
   will differ between environments.

.. note::

   ``/var/lib/libvirt/qemu/ram`` is the default location. The value can be
   set via ``memory_backing_dir`` in ``/etc/libvirt/qemu.conf``, and the
   mountpoint must match the value configured there.

By default, Libvirt with qemu/KVM allocates memory within
``/var/lib/libvirt/qemu/ram/``. To utilize this, you need to have the backing
store mounted at (or above) this location.

#. Create a filesystem on the backing device

   .. code-block:: console

      # mkfs.ext4 /dev/sdb

#. Mount the backing device

   Add the backing device to ``/etc/fstab`` for automatic mounting to
   ``/var/lib/libvirt/qemu/ram``

   Mount the device

   .. code-block:: console

      # mount /dev/sdb /var/lib/libvirt/qemu/ram

Configure Nova Compute for file-backed memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Enable File-backed memory in ``nova-compute``

   Configure Nova to utilize file-backed memory with the capacity of the
   backing store in MiB. 1048576 MiB (1 TiB) is used in this example.

   Edit ``/etc/nova/nova.conf``

   .. code-block:: ini

      [libvirt]
      file_backed_memory=1048576

#. Restart the ``nova-compute`` service
