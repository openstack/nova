Install and configure a compute node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to install and configure the Compute service on a
compute node for Ubuntu, openSUSE and SUSE Linux Enterprise,
and Red Hat Enterprise Linux and CentOS.

The service supports several hypervisors to deploy instances or
virtual machines (VMs). For simplicity, this configuration uses the Quick
EMUlator (QEMU) hypervisor with the kernel-based VM (KVM) extension on compute
nodes that support hardware acceleration for virtual machines.  On legacy
hardware, this configuration uses the generic QEMU hypervisor.  You can follow
these instructions with minor modifications to horizontally scale your
environment with additional compute nodes.

.. note::

   This section assumes that you are following the instructions in this guide
   step-by-step to configure the first compute node. If you want to configure
   additional compute nodes, prepare them in a similar fashion to the first
   compute node in the :ref:`example architectures
   <overview-example-architectures>` section. Each additional compute node
   requires a unique IP address.

.. toctree::
   :glob:

   compute-install-ubuntu.rst
   compute-install-rdo.rst
   compute-install-obs.rst
