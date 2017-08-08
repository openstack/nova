===============================
Hypervisor Configuration Basics
===============================

The node where the ``nova-compute`` service is installed and operates on the
same node that runs all of the virtual machines.  This is referred to as the
compute node in this guide.

By default, the selected hypervisor is KVM. To change to another hypervisor,
change the ``virt_type`` option in the ``[libvirt]`` section of ``nova.conf``
and restart the ``nova-compute`` service.

Specific options for particular hypervisors can be found in
the following sections.
