======================
LXC (Linux containers)
======================

LXC (also known as Linux containers) is a virtualization technology that works
at the operating system level. This is different from hardware virtualization,
the approach used by other hypervisors such as KVM, Xen, and VMware. LXC (as
currently implemented using libvirt in the Compute service) is not a secure
virtualization technology for multi-tenant environments (specifically,
containers may affect resource quotas for other containers hosted on the same
machine). Additional containment technologies, such as AppArmor, may be used to
provide better isolation between containers, although this is not the case by
default.  For all these reasons, the choice of this virtualization technology
is not recommended in production.

If your compute hosts do not have hardware support for virtualization, LXC will
likely provide better performance than QEMU. In addition, if your guests must
access specialized hardware, such as GPUs, this might be easier to achieve with
LXC than other hypervisors.

.. note::

   Some OpenStack Compute features might be missing when running with LXC as
   the hypervisor. See the `hypervisor support matrix
   <http://wiki.openstack.org/HypervisorSupportMatrix>`_ for details.

To enable LXC, ensure the following options are set in ``/etc/nova/nova.conf``
on all hosts running the ``nova-compute`` service.

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = lxc

On Ubuntu, enable LXC support in OpenStack by installing the
``nova-compute-lxc`` package.
