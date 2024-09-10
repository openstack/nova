========================================================
Testing PCI passthrough and SR-IOV with emulated PCI NIC
========================================================
Testing nova PCI and SR-IOV device handling in devstack in general requires
special hardware available in the devstack machine or VM.

Since libvirt 9.3.0 and qemu 8.0.0 the situation is a lot simpler as qemu
is now capable of emulating and intel igb NIC that supports SR-IOV. So
devstack can be run in a VM that has one or more SR-IOV capable NIC while the
host running the devstack VM does not require any special hardware just recent
libvirt and qemu installed.

.. note::
    The emulated igb device used in this doc only useful for testing purposes.
    While network connectivity will work through both the PF and the VF
    interfaces the networking performance will be limited by the qemu
    emulation.

Add SR-IOV capable igb NIC to a devstack VM
-------------------------------------------
You can add an igb NIC to the devstack VM definition:

.. code-block:: bash

    virsh attach-interface --type network --source <libvirt network name> --model igb --config <devstack-domain>

The SR-IOV capability also requires an IOMMU device and split APIC defined in
the domain as well as the q35 machine type.
So make sure you have the following sections:

.. code-block:: xml

    <devices>
        ...
        <iommu model='intel'>
            <driver intremap='on' iotlb='on'/>
        </iommu>
    </devices>

.. code-block:: xml

    <features>
        ..
        <ioapic driver='qemu'/>
    </features>

.. code-block:: xml

    <os>
        ...
        <type arch='x86_64' machine='pc-q35'>hvm</type>
    </os>

Then enable IOMMU in the devstack VM by adding ``intel_iommu=on`` to the kernel
command line.

Using nova to get a VM with SR-IOV capable igb NICs
---------------------------------------------------
If you are using nova 2025.1 (Epoxy) or newer then you can use the
``hw_machine_type=q35``, ``hw_vif_model=igb``, and ``hw_iommu_model=intel``
image properties to request a VM with igb NICs.

Configuring your devstack VM for SR-IOV
---------------------------------------
Follow the `guide <https://docs.openstack.org/neutron/latest/admin/config-sriov.html>`_;
