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

   For information on creating servers with virtual SR-IOV devices, refer to
   the :neutron-doc:`Networking Guide <admin/config-sriov>`.

   **Limitations**

   * Attaching SR-IOV ports to existing servers is not currently supported.
     This is now rejected by the API but previously it fail later in the
     process. See `bug 1708433 <https://bugs.launchpad.net/nova/+bug/1708433>`_
     for details.
   * Cold migration (resize) of servers with SR-IOV devices attached was not
     supported until the 14.0.0 Newton release, see
     `bug 1512800 <https://bugs.launchpad.net/nova/+bug/1512880>`_ for details.

To enable PCI passthrough, follow the steps below.

.. note::

   The PCI device with address ``0000:41:00.0``, the vendor ID of ``8086`` and
   the product ID of ``154d`` is used as an example. This will differ between
   environments.


Configure ``nova-scheduler`` (Controller)
-----------------------------------------

The :program:`nova-scheduler` service must be configured to enable the
``PciPassthroughFilter``. To do this, add this filter to the list of filters
specified in :oslo.config:option:`filter_scheduler.enabled_filters` and set
:oslo.config:option:`filter_scheduler.available_filters` to the default of
``nova.scheduler.filters.all_filters``. For example:

.. code-block:: ini

   [filter_scheduler]
   enabled_filters = ...,PciPassthroughFilter
   available_filters = nova.scheduler.filters.all_filters

Once done, restart the :program:`nova-scheduler` service.


.. _pci-passthrough-alias:

Configure ``nova-api`` (Controller)
-----------------------------------

PCI devices are requested through flavor extra specs, specifically via the
``pci_passthrough:alias`` flavor extra spec. However, the aliases themselves
must be configured. This done via the :oslo.config:option:`pci.alias`
configuration option. For example, to configure a PCI alias ``a1`` to request
a PCI device with a vendor ID of ``0x8086`` and a product ID of ``0x154d``:

.. code-block:: ini

   [pci]
   alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1" }

Refer to :oslo.config:option:`pci.alias` for syntax information.

Once configured, restart the :program:`nova-api` service.

.. important::

   This option must also be configured on compute nodes. This is discussed later
   in this document.


Configure a flavor (API)
------------------------

Once the alias has been configured, it can be used for an flavor extra spec.
For example, to request two of the PCI devices referenced by alias ``a1``, run:

.. code-block:: console

   $ openstack flavor set m1.large --property "pci_passthrough:alias"="a1:2"

For more information about the syntax for ``pci_passthrough:alias``, refer to
:ref:`Flavors <extra-spec-pci-passthrough>`.


Configure host (Compute)
------------------------

To enable PCI passthrough on an x86, Linux-based compute node, the following
are required:

* VT-d enabled in the BIOS
* IOMMU enabled on the host OS, by adding the ``intel_iommu=on`` or
  ``amd_iommu=on`` parameter to the kernel parameters
* Assignable PCIe devices

To enable PCI passthrough on a Hyper-V compute node, the following are
required:

* Windows 10 or Windows / Hyper-V Server 2016 or newer
* VT-d enabled on the host
* Assignable PCI devices

In order to check the requirements above and if there are any assignable PCI
devices, run the following Powershell commands:

.. code-block:: console

    Start-BitsTransfer https://raw.githubusercontent.com/Microsoft/Virtualization-Documentation/master/hyperv-samples/benarm-powershell/DDA/survey-dda.ps1
     .\survey-dda.ps1

If the compute node passes all the requirements, the desired assignable PCI
devices to be disabled and unmounted from the host, in order to be assignable
by Hyper-V. The following can be read for more details: `Hyper-V PCI
passthrough`__.

.. __: https://devblogs.microsoft.com/scripting/passing-through-devices-to-hyper-v-vms-by-using-discrete-device-assignment/


Configure ``nova-compute`` (Compute)
------------------------------------

Once PCI passthrough has been configured for the host, :program:`nova-compute`
must be configured to allow the PCI device to pass through to VMs. This is done
using the :oslo.config:option:`pci.passthrough_whitelist` option. For example,
to enable passthrough of a specific device using its address:

.. code-block:: ini

   [pci]
   passthrough_whitelist = { "address": "0000:41:00.0" }

Refer to :oslo.config:option:`pci.passthrough_whitelist` for syntax information.

Alternatively, to enable passthrough of all devices with the same product and
vendor ID:

.. code-block:: ini

   [pci]
   passthrough_whitelist = { "vendor_id": "8086", "product_id": "154d" }

If using vendor and product IDs, all PCI devices matching the ``vendor_id`` and
``product_id`` are added to the pool of PCI devices available for passthrough
to VMs.

In addition, it is necessary to configure the :oslo.config:option:`pci.alias`
option on the compute node too. This is required to allow resizes of guests
with PCI devices. This should be identical to the alias configured
:ref:`previously <pci-passthrough-alias>`. For example:

.. code-block:: ini

   [pci]
   alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1" }

Refer to :oslo.config:option:`pci.alias` for syntax information.

Once configured, restart the :program:`nova-compute` service.


Create instances with PCI passthrough devices
---------------------------------------------

The :program:`nova-scheduler` service selects a destination host that has PCI
devices available that match the ``alias`` specified in the flavor.

.. code-block:: console

   # openstack server create --flavor m1.large --image cirros-0.3.5-x86_64-uec --wait test-pci
