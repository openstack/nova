=========
Virtuozzo
=========

Virtuozzo 7.0.0 (or newer), or its community edition OpenVZ, provides both
types of virtualization: Kernel Virtual Machines and OS Containers.  The type
of instance to span is chosen depending on the ``hw_vm_type`` property of an
image.

.. note::

   Some OpenStack Compute features may be missing when running with Virtuozzo
   as the hypervisor. See :doc:`/user/support-matrix` for details.

To enable Virtuozzo Containers, set the following options in
``/etc/nova/nova.conf`` on all hosts running the ``nova-compute`` service.

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver
   force_raw_images = False

   [libvirt]
   virt_type = parallels
   images_type = ploop
   connection_uri = parallels:///system
   inject_partition = -2

To enable Virtuozzo Virtual Machines, set the following options in
``/etc/nova/nova.conf`` on all hosts running the ``nova-compute`` service.

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = parallels
   images_type = qcow2
   connection_uri = parallels:///system
