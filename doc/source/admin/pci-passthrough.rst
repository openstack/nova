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

.. versionchanged:: 26.0.0 (Zed):
  PCI passthrough device inventories now can be tracked in Placement.
  For more information, refer to :ref:`pci-tracking-in-placement`.

.. versionchanged:: 26.0.0 (Zed):
  The nova-compute service will refuse to start if both the parent PF and its
  children VFs are configured in :oslo.config:option:`pci.device_spec`.
  For more information, refer to :ref:`pci-tracking-in-placement`.

.. versionchanged:: 26.0.0 (Zed):
  The nova-compute service will refuse to start with
  :oslo.config:option:`pci.device_spec` configuration that uses the
  ``devname`` field.

.. versionchanged:: 27.0.0 (2023.1 Antelope):
   Nova provides Placement based scheduling support for servers with flavor
   based PCI requests. This support is disable by default.

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
using the :oslo.config:option:`pci.device_spec` option. For example,
assuming our sample PCI device has a PCI address of ``41:00.0`` on each host:

.. code-block:: ini

   [pci]
   device_spec = { "address": "0000:41:00.0" }

Refer to :oslo.config:option:`pci.device_spec` for syntax information.

Alternatively, to enable passthrough of all devices with the same product and
vendor ID:

.. code-block:: ini

   [pci]
   device_spec = { "vendor_id": "8086", "product_id": "154d" }

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

When specified in :oslo.config:option:`pci.device_spec` some tags
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

.. note::

   The use of ``"physical_network": null`` is only supported in single segment
   networks. This is due to Nova not supporting multisegment networks for
   SR-IOV ports. See
   `bug 1983570 <https://bugs.launchpad.net/nova/+bug/1983570>`_ for details.

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
     errors encountered while programming a VLAN are ignored if VLAN clearing is
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

.. _pci-tracking-in-placement:

PCI tracking in Placement
-------------------------
.. note::
   The feature described below are optional and disabled by default in nova
   26.0.0. (Zed). The legacy PCI tracker code path is still supported and
   enabled. The Placement PCI tracking can be enabled via the
   :oslo.config:option:`pci.report_in_placement` configuration. But please note
   that once it is enabled on a given compute host it cannot be disabled there
   any more.

Since nova 26.0.0 (Zed) PCI passthrough device inventories are tracked in
Placement. If a PCI device exists on the hypervisor and
matches one of the device specifications configured via
:oslo.config:option:`pci.device_spec` then Placement will have a representation
of the device. Each PCI device of type ``type-PCI`` and ``type-PF`` will be
modeled as a Placement resource provider (RP) with the name
``<hypervisor_hostname>_<pci_address>``. A devices with type ``type-VF`` is
represented by its parent PCI device, the PF, as resource provider.

By default nova will use ``CUSTOM_PCI_<vendor_id>_<product_id>`` as the
resource class in PCI inventories in Placement. However the name of the
resource class can be customized via the ``resource_class`` tag in the
:oslo.config:option:`pci.device_spec` option. There is also a new ``traits``
tag in that configuration that allows specifying a list of placement traits to
be added to the resource provider representing the matching PCI devices.

.. note::
   In nova 26.0.0 (Zed) the Placement resource tracking of PCI devices does not
   support SR-IOV devices intended to be consumed via Neutron ports and
   therefore having ``physical_network`` tag in
   :oslo.config:option:`pci.device_spec`. Such devices are supported via the
   legacy PCI tracker code path in Nova.

.. note::
   Having different resource class or traits configuration for VFs under the
   same parent PF is not supported and the nova-compute service will refuse to
   start with such configuration.

.. important::
   While nova supported configuring both the PF and its children VFs for PCI
   passthrough in the past, it only allowed consuming either the parent PF or
   its children VFs. Since 26.0.0. (Zed) the nova-compute service will
   enforce the same rule for the configuration as well and will refuse to
   start if both the parent PF and its VFs are configured.

.. important::
   While nova supported configuring PCI devices by device name via the
   ``devname`` parameter in :oslo.config:option:`pci.device_spec` in the past,
   this proved to be problematic as the netdev name of a PCI device could
   change for multiple reasons during hypervisor reboot. So since nova 26.0.0
   (Zed) the nova-compute service will refuse to start with such configuration.
   It is suggested to use the PCI address of the device instead.

The nova-compute service makes sure that existing instances with PCI
allocations in the nova DB will have a corresponding PCI allocation in
placement. This allocation healing also acts on any new instances regardless of
the status of the scheduling part of this feature to make sure that the nova
DB and placement are in sync. There is one limitation of the healing logic.
It assumes that there is no in-progress migration when the nova-compute service
is upgraded. If there is an in-progress migration then the PCI allocation on
the source host of the migration will not be healed. The placement view will be
consistent after such migration is completed or reverted.

Reconfiguring the PCI devices on the hypervisor or changing the
:oslo.config:option:`pci.device_spec` configuration option and restarting the
nova-compute service is supported in the following cases:

* new devices are added
* devices without allocation are removed

Removing a device that has allocations is not supported. If a device having any
allocation is removed then the nova-compute service will keep the device and
the allocation exists in the nova DB and in placement and logs a warning. If
a device with any allocation is reconfigured in a way that an allocated PF is
removed and VFs from the same PF is configured (or vice versa) then
nova-compute will refuse to start as it would create a situation where both
the PF and its VFs are made available for consumption.

Since nova 27.0.0 (2023.1 Antelope) scheduling and allocation of PCI devices
in Placement can also be enabled via
:oslo.config:option:`filter_scheduler.pci_in_placement`. Please note that this
should only be enabled after all the computes in the system is configured to
report PCI inventory in Placement via
enabling :oslo.config:option:`pci.report_in_placement`. In Antelope flavor
based PCI requests are support but Neutron port base PCI requests are not
handled in Placement.

If you are upgrading from an earlier version with already existing servers with
PCI usage then you must enable :oslo.config:option:`pci.report_in_placement`
first on all your computes having PCI allocations and then restart the
nova-compute service, before you enable
:oslo.config:option:`filter_scheduler.pci_in_placement`. The compute service
will heal the missing PCI allocation in placement during startup and will
continue healing missing allocations for future servers until the scheduling
support is enabled.

If a flavor requests multiple ``type-VF`` devices via
:nova:extra-spec:`pci_passthrough:alias` then it is important to consider the
value of :nova:extra-spec:`group_policy` as well. The value ``none``
allows nova to select VFs from the same parent PF to fulfill the request. The
value ``isolate`` restricts nova to select each VF from a different parent PF
to fulfill the request. If :nova:extra-spec:`group_policy` is not provided in
such flavor then it will defaulted to ``none``.

Symmetrically with the ``resource_class`` and ``traits`` fields of
:oslo.config:option:`pci.device_spec` the :oslo.config:option:`pci.alias`
configuration option supports requesting devices by Placement resource class
name via the ``resource_class`` field and also support requesting traits to
be present on the selected devices via the ``traits`` field in the alias. If
the ``resource_class`` field is not specified in the alias then it is defaulted
by nova to ``CUSTOM_PCI_<vendor_id>_<product_id>``.

For deeper technical details please read the `nova specification. <https://specs.openstack.org/openstack/nova-specs/specs/zed/approved/pci-device-tracking-in-placement.html>`_


Virtual IOMMU support
---------------------

With provided :nova:extra-spec:`hw:viommu_model` flavor extra spec or equivalent
image metadata property ``hw_viommu_model`` and with the guest CPU architecture
and OS allows, we can enable vIOMMU in libvirt driver.

.. note::

    Enable vIOMMU might introduce significant performance overhead.
    You can see performance comparison table from
    `AMD vIOMMU session on KVM Forum 2021`_.
    For the above reason, vIOMMU should only be enabled for workflow that
    require it.

.. _`AMD vIOMMU session on KVM Forum 2021`: https://static.sched.com/hosted_files/kvmforum2021/da/vIOMMU%20KVM%20Forum%202021%20-%20v4.pdf

Here are four possible values allowed for ``hw:viommu_model``
(and ``hw_viommu_model``):

**virtio**
    Supported on Libvirt since 8.3.0, for Q35 and ARM virt guests.

**smmuv3**
    Supported on Libvirt since 5.5.0, for ARM virt guests.
**intel**
    Supported for for Q35 guests.

**auto**
    This option will translate to ``virtio`` if Libvirt supported,
    else ``intel`` on X86 (Q35) and ``smmuv3`` on AArch64.

For the viommu attributes:

* ``intremap``, ``caching_mode``, and ``iotlb``
  options for viommu (These attributes are driver attributes defined in
  `Libvirt IOMMU Domain`_) will direcly enabled.

* ``eim`` will directly enabled if machine type is Q35.
  ``eim`` is driver attribute defined in `Libvirt IOMMU Domain`_.

.. note::

    eim(Extended Interrupt Mode) attribute (with possible values on and off)
    can be used to configure Extended Interrupt Mode.
    A q35 domain with split I/O APIC (as described in hypervisor features),
    and both interrupt remapping and EIM turned on for the IOMMU, will be
    able to use more than 255 vCPUs. Since 3.4.0 (QEMU/KVM only).

* ``aw_bits`` attribute can used to set the address width to allow mapping
  larger iova addresses in the guest. Since Qemu current supported
  values are 39 and 48, we directly set this to larger width (48)
  if Libvirt supported.
  ``aw_bits`` is driver attribute defined in `Libvirt IOMMU Domain`_.

.. _`Libvirt IOMMU Domain`: https://libvirt.org/formatdomain.html#iommu-devices
