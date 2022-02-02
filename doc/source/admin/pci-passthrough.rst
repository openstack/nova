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

PCI devices are requested through flavor extra specs, specifically via the
:nova:extra-spec:`pci_passthrough:alias` flavor extra spec.
This guide demonstrates how to enable PCI passthrough for a type of PCI device
with a vendor ID of ``8086`` and a product ID of ``154d`` - an Intel X520
Network Adapter - by mapping them to the alias ``a1``.
You should adjust the instructions for other devices with potentially different
capabilities.

.. note::

   For information on creating servers with SR-IOV network interfaces, refer to
   the :neutron-doc:`Networking Guide <admin/config-sriov>`.

   **Limitations**

   * Attaching SR-IOV ports to existing servers was not supported until the
     22.0.0 Victoria release. Due to various bugs in libvirt and qemu we
     recommend to use at least libvirt version 6.0.0 and at least qemu version
     4.2.
   * Cold migration (resize) of servers with SR-IOV devices attached was not
     supported until the 14.0.0 Newton release, see
     `bug 1512800 <https://bugs.launchpad.net/nova/+bug/1512880>`_ for details.

.. note::

   Nova only supports PCI addresses where the fields are restricted to the
   following maximum value:

   * domain - 0xFFFF
   * bus - 0xFF
   * slot - 0x1F
   * function - 0x7

   Nova will ignore PCI devices reported by the hypervisor if the address is
   outside of these ranges.

Enabling PCI passthrough
------------------------

Configure compute host
~~~~~~~~~~~~~~~~~~~~~~

To enable PCI passthrough on an x86, Linux-based compute node, the following
are required:

* VT-d enabled in the BIOS
* IOMMU enabled on the host OS, e.g. by adding the ``intel_iommu=on`` or
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

Configure ``nova-compute``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Once PCI passthrough has been configured for the host, :program:`nova-compute`
must be configured to allow the PCI device to pass through to VMs. This is done
using the :oslo.config:option:`pci.passthrough_whitelist` option. For example,
assuming our sample PCI device has a PCI address of ``41:00.0`` on each host:

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
option, which is a JSON-style configuration option that allows you to map a
given device type, identified by the standard PCI ``vendor_id`` and (optional)
``product_id`` fields, to an arbitrary name or *alias*. This alias can then be
used to request a PCI device using the :nova:extra-spec:`pci_passthrough:alias`
flavor extra spec, as discussed previously.
For our sample device with a vendor ID of ``0x8086`` and a product ID of
``0x154d``, this would be:

.. code-block:: ini

   [pci]
   alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1" }

It's important to note the addition of the ``device_type`` field. This is
necessary because this PCI device supports SR-IOV. The ``nova-compute`` service
categorizes devices into one of three types, depending on the capabilities the
devices report:

``type-PF``
  The device supports SR-IOV and is the parent or root device.

``type-VF``
  The device is a child device of a device that supports SR-IOV.

``type-PCI``
  The device does not support SR-IOV.

By default, it is only possible to attach ``type-PCI`` devices using PCI
passthrough. If you wish to attach ``type-PF`` or ``type-VF`` devices, you must
specify the ``device_type`` field in the config option. If the device was a
device that did not support SR-IOV, the ``device_type`` field could be omitted.

Refer to :oslo.config:option:`pci.alias` for syntax information.

.. important::

   This option must also be configured on controller nodes. This is discussed later
   in this document.

Once configured, restart the :program:`nova-compute` service.

Special Tags
^^^^^^^^^^^^

When specified in :oslo.config:option:`pci.passthrough_whitelist` some tags
have special meaning:

``physical_network``
  Associates a device with a physical network label which corresponds to the
  ``physical_network`` attribute of a network segment object in Neutron. For
  virtual networks such as overlays a value of ``null`` should be specified
  as follows: ``"physical_network": null``. In the case of physical networks,
  this tag is used to supply the metadata necessary for identifying a switched
  fabric to which a PCI device belongs and associate the port with the correct
  network segment in the networking backend. Besides typical SR-IOV scenarios,
  this tag can be used for remote-managed devices in conjunction with the
  ``remote_managed`` tag.

``remote_managed``
  Used to specify whether a PCI device is managed remotely or not. By default,
  devices are implicitly tagged as ``"remote_managed": "false"`` but and they
  must be tagged as ``"remote_managed": "true"`` if ports with
  ``VNIC_TYPE_REMOTE_MANAGED`` are intended to be used. Once that is done,
  those PCI devices will not be available for allocation for regular
  PCI passthrough use. Specifying ``"remote_managed": "true"`` is only valid
  for SR-IOV VFs and specifying it for PFs is prohibited.

  .. important::
     It is recommended that PCI VFs that are meant to be remote-managed
     (e.g. the ones provided by SmartNIC DPUs) are tagged as remote-managed in
     order to prevent them from being allocated for regular PCI passthrough since
     they have to be programmed accordingly at the host that has access to the
     NIC switch control plane. If this is not done, instances requesting regular
     SR-IOV ports may get a device that will not be configured correctly and
     will not be usable for sending network traffic.

  .. important::
     For the Libvirt virt driver, clearing a VLAN by programming VLAN 0 must not
     result in errors in the VF kernel driver at the compute host. Before v8.1.0
     Libvirt clears a VLAN before passing a VF through to the guest which may
     result in an error depending on your driver and kernel version (see, for
     example, `this bug <https://bugs.launchpad.net/ubuntu/+source/linux/+bug/1957753>`_
     which discusses a case relevant to one driver). As of Libvirt v8.1.0, EPERM
     errors encountered while programming a VLAN are ignored if VLAN clearning is
     not explicitly requested in the device XML.

``trusted``
  If a port is requested to be trusted by specifying an extra option during
  port creation via ``--binding-profile trusted=true``, only devices tagged as
  ``trusted: "true"`` will be allocated to instances. Nova will then configure
  those devices as trusted by the network controller through its PF device driver.
  The specific set of features allowed by the trusted mode of a VF will differ
  depending on the network controller itself, its firmware version and what a PF
  device driver version allows to pass to the NIC. Common features to be affected
  by this tag are changing the VF MAC address, enabling promiscuous mode or
  multicast promiscuous mode.

  .. important::
     While the ``trusted tag`` does not directly conflict with the
     ``remote_managed`` tag, network controllers in SmartNIC DPUs may prohibit
     setting the ``trusted`` mode on a VF via a PF device driver in the first
     place. It is recommended to test specific devices, drivers and firmware
     versions before assuming this feature can be used.


Configure ``nova-scheduler``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

Configure ``nova-api``
~~~~~~~~~~~~~~~~~~~~~~

It is necessary to also configure the :oslo.config:option:`pci.alias` config
option on the controller. This configuration should match the configuration
found on the compute nodes. For example:

.. code-block:: ini

   [pci]
   alias = { "vendor_id":"8086", "product_id":"154d", "device_type":"type-PF", "name":"a1", "numa_policy":"preferred" }

Refer to :oslo.config:option:`pci.alias` for syntax information.
Refer to :ref:`Affinity  <pci-numa-affinity-policy>` for ``numa_policy``
information.

Once configured, restart the :program:`nova-api` service.


Configuring a flavor or image
-----------------------------

Once the alias has been configured, it can be used for an flavor extra spec.
For example, to request two of the PCI devices referenced by alias ``a1``, run:

.. code-block:: console

   $ openstack flavor set m1.large --property "pci_passthrough:alias"="a1:2"

For more information about the syntax for ``pci_passthrough:alias``, refer to
:doc:`the documentation </configuration/extra-specs>`.


.. _pci-numa-affinity-policy:

PCI-NUMA affinity policies
--------------------------

By default, the libvirt driver enforces strict NUMA affinity for PCI devices,
be they PCI passthrough devices or neutron SR-IOV interfaces. This means that
by default a PCI device must be allocated from the same host NUMA node as at
least one of the instance's CPUs. This isn't always necessary, however, and you
can configure this policy using the
:nova:extra-spec:`hw:pci_numa_affinity_policy` flavor extra spec or equivalent
image metadata property. There are three possible values allowed:

**required**
    This policy means that nova will boot instances with PCI devices **only**
    if at least one of the NUMA nodes of the instance is associated with these
    PCI devices. It means that if NUMA node info for some PCI devices could not
    be determined, those PCI devices wouldn't be consumable by the instance.
    This provides maximum performance.

**socket**
    This policy means that the PCI device must be affined to the same host
    socket as at least one of the guest NUMA nodes. For example, consider a
    system with two sockets, each with two NUMA nodes, numbered node 0 and node
    1 on socket 0, and node 2 and node 3 on socket 1. There is a PCI device
    affined to node 0. An PCI instance with two guest NUMA nodes and the
    ``socket`` policy can be affined to either:

    * node 0 and node 1
    * node 0 and node 2
    * node 0 and node 3
    * node 1 and node 2
    * node 1 and node 3

    The instance cannot be affined to node 2 and node 3, as neither of those
    are on the same socket as the PCI device. If the other nodes are consumed
    by other instances and only nodes 2 and 3 are available, the instance
    will not boot.

**preferred**
    This policy means that ``nova-scheduler`` will choose a compute host
    with minimal consideration for the NUMA affinity of PCI devices.
    ``nova-compute`` will attempt a best effort selection of PCI devices
    based on NUMA affinity, however, if this is not possible then
    ``nova-compute`` will fall back to scheduling on a NUMA node that is not
    associated with the PCI device.

**legacy**
    This is the default policy and it describes the current nova behavior.
    Usually we have information about association of PCI devices with NUMA
    nodes. However, some PCI devices do not provide such information. The
    ``legacy`` value will mean that nova will boot instances with PCI device
    if either:

    * The PCI device is associated with at least one NUMA nodes on which the
      instance will be booted

    * There is no information about PCI-NUMA affinity available

For example, to configure a flavor to use the ``preferred`` PCI NUMA affinity
policy for any neutron SR-IOV interfaces attached by the user:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:pci_numa_affinity_policy=preferred

You can also configure this for PCI passthrough devices by specifying the
policy in the alias configuration via :oslo.config:option:`pci.alias`. For more
information, refer to :oslo.config:option:`the documentation <pci.alias>`.
