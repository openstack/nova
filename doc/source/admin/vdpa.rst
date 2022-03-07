============================
Using ports vnic_type='vdpa'
============================
.. versionadded:: 23.0.0 (Wallaby)

   Introduced support for vDPA.

.. important::
   The functionality described below is only supported by the
   libvirt/KVM virt driver.

The kernel vDPA (virtio Data Path Acceleration) framework
provides a vendor independent framework for offloading data-plane
processing to software or hardware virtio device backends.
While the kernel vDPA framework supports many types of vDPA devices,
at this time nova only support ``virtio-net`` devices
using the ``vhost-vdpa`` front-end driver. Support for ``virtio-blk`` or
``virtio-gpu`` may be added in the future but is not currently planned
for any specific release.

vDPA device tracking
~~~~~~~~~~~~~~~~~~~~
When implementing support for vDPA based neutron ports one of the first
decisions nova had to make was how to model the availability of vDPA devices
and the capability to virtualize vDPA devices. As the initial use-case
for this technology was to offload networking to hardware offload OVS via
neutron ports the decision was made to extend the existing PCI tracker that
is used for SR-IOV and pci-passthrough to support vDPA devices. As a result
a simplification was made to assume that the parent device of a vDPA device
is an SR-IOV Virtual Function (VF). As a result software only vDPA device such
as those created by the kernel ``vdpa-sim`` sample module are not supported.

To make vDPA device available to be scheduled to guests the operator should
include the device using the PCI address or vendor ID and product ID of the
parent VF in the PCI ``device_spec``.
See: :nova-doc:`pci-passthrough <admin/pci-passthrough>` for details.

Nova will not create the VFs or vDPA devices automatically. It is expected
that the operator will allocate them before starting the nova-compute agent.
While no specific mechanisms is prescribed to do this udev rules or systemd
service files are generally the recommended approach to ensure the devices
are created consistently across reboots.

.. note::
   As vDPA is an offload only for the data plane and not the control plane a
   vDPA control plane is required to properly support vDPA device passthrough.
   At the time of writing only hardware offloaded OVS is supported when using
   vDPA with nova. Because of this vDPA devices cannot be requested using the
   PCI alias. While nova could allow vDPA devices to be requested by the
   flavor using a PCI alias we would not be able to correctly configure the
   device as there would be no suitable control plane. For this reason vDPA
   devices are currently only consumable via neutron ports.

Virt driver support
~~~~~~~~~~~~~~~~~~~

Supporting neutron ports with ``vnic_type=vdpa`` depends on the capability
of the virt driver. At this time only the ``libvirt`` virt driver with KVM
is fully supported. QEMU may also work but is untested.

vDPA support depends on kernel 5.7+, Libvirt 6.9.0+ and QEMU 5.1+.

vDPA lifecycle operations
~~~~~~~~~~~~~~~~~~~~~~~~~

At this time vDPA ports can only be added to a VM when it is first created.
To do this the normal SR-IOV workflow is used where by the port is first created
in neutron and passed into nova as part of the server create request.

.. code-block:: bash

   openstack port create --network <my network> --vnic-type vdpa vdpa-port
   openstack server create --flavor <my-flavor> --image <my-image> --port <vdpa-port uuid> vdpa-vm

When vDPA support was first introduced no move operations were supported.
As this documentation was added in the change that enabled some move operations
The following should be interpreted both as a retrospective and future looking
viewpoint and treated as a living document which will be updated as functionality evolves.

23.0.0: initial support is added for creating a VM with vDPA ports, move operations
are blocked in the API but implemented in code.
26.0.0: support for all move operation except live migration is tested and api blocks are removed.
25.x.y: (planned) api block removal backported to stable/Yoga
24.x.y: (planned) api block removal backported to stable/Xena
23.x.y: (planned) api block removal backported to stable/wallaby
26.0.0: (in progress) interface attach/detach, suspend/resume and hot plug live migration
are implemented to fully support all lifecycle operations on instances with vDPA ports.

.. note::
   The ``(planned)`` and ``(in progress)`` qualifiers will be removed when those items are
   completed. If your current version of the document contains those qualifiers then those
   lifecycle operations are unsupported.
