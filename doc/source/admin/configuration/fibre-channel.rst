=================================
Configuring Fibre Channel Support
=================================

Fibre Channel support in OpenStack Compute is remote block storage attached to
compute nodes for VMs.

.. todo:: This below statement needs to be verified for current release

Fibre Channel supported only the KVM hypervisor.

Compute and Block Storage support Fibre Channel automatic zoning on Brocade and
Cisco switches. On other hardware Fibre Channel arrays must be pre-zoned or
directly attached to the KVM hosts.

KVM host requirements
~~~~~~~~~~~~~~~~~~~~~

You must install these packages on the KVM host:

``sysfsutils``
  Nova uses the ``systool`` application in this package.

``sg3-utils`` or ``sg3_utils``
  Nova uses the ``sg_scan`` and ``sginfo`` applications.

Installing the ``multipath-tools`` or ``device-mapper-multipath`` package is
optional.
