========================================
Attaching physical PCI devices to guests
========================================

The PCI passthrough feature in OpenStack allows full access and direct control
of a physical PCI device in guests. This mechanism is generic for any kind of
PCI device, and runs with a Network Interface Card (NIC), Graphics Processing
Unit (GPU), or any other devices that can be attached to a PCI bus. Correct
driver installation is the only requirement for the guest to properly use the
devices.

Some PCI devices provide Single Root I/O Virtualization and Sharing (SR-IOV)
capabilities. When SR-IOV is used, a physical device is virtualized and appears
as multiple PCI devices. Virtual PCI devices are assigned to the same or
different guests. In the case of PCI passthrough, the full physical device is
assigned to only one guest and cannot be shared.

.. note::

   For information on creating servers with virtual SR-IOV devices to guests,
   refer to the `Networking Guide`_. Attaching SR-IOV ports to existing servers
   is not currently supported, see
   `bug 1708433 <https://bugs.launchpad.net/nova/+bug/1708433>`_ for details.

To enable PCI passthrough, follow the steps below:

#. Configure nova-scheduler (Controller)

#. Configure nova-api (Controller)**

#. Configure a flavor (Controller)

#. Enable PCI passthrough (Compute)

#. Configure PCI devices in nova-compute (Compute)

.. note::

   The PCI device with address ``0000:41:00.0`` is used as an example. This
   will differ between environments.

Configure nova-scheduler (Controller)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Configure ``nova-scheduler`` as specified in `Configure nova-scheduler`_.

#. Restart the ``nova-scheduler`` service.

Configure nova-api (Controller)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Specify the PCI alias for the device.

   Configure a PCI alias ``a1`` to request a PCI device with a ``vendor_id`` of
   ``0x8086`` and a ``product_id`` of ``0x154d``. The ``vendor_id`` and
   ``product_id`` correspond the PCI device with address ``0000:41:00.0``.

   Edit ``/etc/nova/nova.conf``:

   .. code-block:: ini

      [pci]
      alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1" }

   For more information about the syntax of ``alias``, refer to
   :doc:`/configuration/config`.

#. Restart the ``nova-api`` service.

Configure a flavor (Controller)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure a flavor to request two PCI devices, each with ``vendor_id`` of
``0x8086`` and ``product_id`` of ``0x154d``:

.. code-block:: console

   # openstack flavor set m1.large --property "pci_passthrough:alias"="a1:2"

For more information about the syntax for ``pci_passthrough:alias``, refer to
:doc:`/admin/flavors`.

Enable PCI passthrough (Compute)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable VT-d and IOMMU. For more information, refer to steps one and two in
`Create Virtual Functions`_.

Configure PCI devices (Compute)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Configure ``nova-compute`` to allow the PCI device to pass through to
   VMs. Edit ``/etc/nova/nova.conf``:

   .. code-block:: ini

      [pci]
      passthrough_whitelist = { "address": "0000:41:00.0" }

   Alternatively specify multiple PCI devices using whitelisting:

   .. code-block:: ini

      [pci]
      passthrough_whitelist = { "vendor_id": "8086", "product_id": "10fb" }

   All PCI devices matching the ``vendor_id`` and ``product_id`` are added to
   the pool of PCI devices available for passthrough to VMs.

   For more information about the syntax of ``passthrough_whitelist``,
   refer to :doc:`/configuration/config`.

#. Specify the PCI alias for the device.

   From the Newton release, to resize guest with PCI device, configure the PCI
   alias on the compute node as well.

   Configure a PCI alias ``a1`` to request a PCI device with a ``vendor_id`` of
   ``0x8086`` and a ``product_id`` of ``0x154d``. The ``vendor_id`` and
   ``product_id`` correspond the PCI device with address ``0000:41:00.0``.

   Edit ``/etc/nova/nova.conf``:

   .. code-block:: ini

      [pci]
      alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1" }

   For more information about the syntax of ``alias``, refer to :doc:`/configuration/config`.

#. Restart the ``nova-compute`` service.

Create instances with PCI passthrough devices
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``nova-scheduler`` selects a destination host that has PCI devices
available with the specified ``vendor_id`` and ``product_id`` that matches the
``alias`` from the flavor.

.. code-block:: console

   # openstack server create --flavor m1.large --image cirros-0.3.5-x86_64-uec --wait test-pci

.. Links
.. _`Create Virtual Functions`: https://docs.openstack.org/neutron/latest/admin/config-sriov.html#create-virtual-functions-compute
.. _`Configure nova-scheduler`: https://docs.openstack.org/neutron/latest/admin/config-sriov.html#configure-nova-scheduler-controller
.. _`Networking Guide`: https://docs.openstack.org/neutron/latest/admin/config-sriov.html
