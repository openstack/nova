=======================
Networking with neutron
=======================

While nova uses the :neutron-doc:`OpenStack Networking service (neutron) <>` to
provide network connectivity for instances, nova itself provides some
additional features not possible with neutron alone. These are described below.


SR-IOV
------

.. versionchanged:: 2014.2

   The feature described below was first introduced in the Juno release.

The SR-IOV specification defines a standardized mechanism to virtualize PCIe
devices. This mechanism can virtualize a single PCIe Ethernet controller to
appear as multiple PCIe devices. Each device can be directly assigned to an
instance, bypassing the hypervisor and virtual switch layer. As a result, users
are able to achieve low latency and near-line wire speed.

A full guide on configuring and using SR-IOV is provided in the
:neutron-doc:`OpenStack Networking service documentation
<admin/config-sriov.html>`


NUMA Affinity
-------------

.. versionadded:: 18.0.0

   The feature described below was first introduced in the Rocky release.

.. important::

   The functionality described below is currently only supported by the
   libvirt/KVM driver.

As described in :doc:`cpu-topologies`, NUMA is a computer architecture where
memory accesses to certain regions of system memory can have higher latencies
than other regions, depending on the CPU(s) your process is running on. This
effect extends to devices connected to the PCIe bus, a concept known as NUMA
I/O. Many Network Interface Cards (NICs) connect using the PCIe interface,
meaning they are susceptible to the ill-effects of poor NUMA affinitization. As
a result, NUMA locality must be considered when creating an instance where high
dataplane performance is a requirement.

Fortunately, nova provides functionality to ensure NUMA affinitization is
provided for instances using neutron. How this works depends on the type of
port you are trying to use.

.. todo::

   Add documentation for PCI NUMA affinity and PCI policies and link to it from
   here.

For SR-IOV ports, virtual functions, which are PCI devices, are attached to the
instance. This means the instance can benefit from the NUMA affinity guarantees
provided for PCI devices. This happens automatically.

For all other types of ports, some manual configuration is required.

#. Identify the type of network(s) you wish to provide NUMA affinity for.

   - If a network is an L2-type network (``provider:network_type`` of ``flat``
     or ``vlan``), affinity of the network to given NUMA node(s) can vary
     depending on value of the ``provider:physical_network`` attribute of the
     network, commonly referred to as the *physnet* of the network. This is
     because most neutron drivers map each *physnet* to a different bridge, to
     which multiple NICs are attached, or to a different (logical) NIC.

   - If a network is an L3-type networks (``provider:network_type`` of
     ``vxlan``, ``gre`` or ``geneve``), all traffic will use the device to
     which the *endpoint IP* is assigned. This means all L3 networks on a given
     host will have affinity to the same NUMA node(s). Refer to
     :neutron-doc:`the neutron documentation
     <admin/intro-overlay-protocols.html>` for more information.

#. Determine the NUMA affinity of the NICs attached to the given network(s).

   How this should be achieved varies depending on the switching solution used
   and whether the network is a L2-type network or an L3-type networks.

   Consider an L2-type network using the Linux Bridge mechanism driver. As
   noted in the :neutron-doc:`neutron documentation
   <admin/deploy-lb-selfservice.html>`, *physnets* are mapped to interfaces
   using the ``[linux_bridge] physical_interface_mappings`` configuration
   option. For example:

   .. code-block:: ini

      [linux_bridge]
      physical_interface_mappings = provider:PROVIDER_INTERFACE

   Once you have the device name, you can query *sysfs* to retrieve the NUMA
   affinity for this device. For example:

   .. code-block:: shell

      $ cat /sys/class/net/PROVIDER_INTERFACE/device/numa_node

   For an L3-type network using the Linux Bridge mechanism driver, the device
   used will be configured using protocol-specific endpoint IP configuration
   option. For VXLAN, this is the ``[vxlan] local_ip`` option. For example:

   .. code-block:: ini

      [vxlan]
      local_ip = OVERLAY_INTERFACE_IP_ADDRESS

   Once you have the IP address in question, you can use :command:`ip` to
   identify the device that has been assigned this IP address and from there
   can query the NUMA affinity using *sysfs* as above.

   .. note::

      The example provided above is merely that: an example. How one should
      identify this information can vary massively depending on the driver
      used, whether bonding is used, the type of network used, etc.

#. Configure NUMA affinity in ``nova.conf``.

   Once you have identified the NUMA affinity of the devices used for your
   networks, you need to configure this in ``nova.conf``. As before, how this
   should be achieved varies depending on the type of network.

   For L2-type networks, NUMA affinity is defined based on the
   ``provider:physical_network`` attribute of the network. There are two
   configuration options that must be set:

   ``[neutron] physnets``
     This should be set to the list of physnets for which you wish to provide
     NUMA affinity. Refer to the :oslo.config:option:`documentation
     <neutron.physnets>` for more information.

   ``[neutron_physnet_{physnet}] numa_nodes``
     This should be set to the list of NUMA node(s) that networks with the
     given ``{physnet}`` should be affinitized to.

   For L3-type networks, NUMA affinity is defined globally for all tunneled
   networks on a given host. There is only one configuration option that must
   be set:

   ``[neutron_tunneled] numa_nodes``
     This should be set to a list of one or NUMA nodes to which instances using
     tunneled networks will be affinitized.

#. Configure a NUMA topology for instance flavor(s)

   For network NUMA affinity to have any effect, the instance must have a NUMA
   topology itself. This can be configured explicitly, using the
   ``hw:numa_nodes`` extra spec, or implicitly through the use of CPU pinning
   (``hw:cpu_policy=dedicated``) or PCI devices. For more information, refer to
   :doc:`cpu-topologies`.

Examples
~~~~~~~~

Take an example for deployment using L2-type networks first.

.. code-block:: ini

   [neutron]
   physnets = foo,bar

   [neutron_physnet_foo]
   numa_nodes = 0

   [neutron_physnet_bar]
   numa_nodes = 2, 3

This configuration will ensure instances using one or more L2-type networks
with ``provider:physical_network=foo`` must be scheduled on host cores from
NUMA nodes 0, while instances using one or more networks with
``provider:physical_network=bar`` must be scheduled on host cores from both
NUMA nodes 2 and 3. For the latter case, it will be necessary to split the
guest across two or more host NUMA nodes using the ``hw:numa_nodes``
:ref:`flavor extra spec <extra-specs-numa-topology>`.

Now, take an example for a deployment using L3 networks.

.. code-block:: ini

   [neutron_tunneled]
   numa_nodes = 0

This is much simpler as all tunneled traffic uses the same logical interface.
As with the L2-type networks, this configuration will ensure instances using
one or more L3-type networks must be scheduled on host cores from NUMA node 0.
It is also possible to define more than one NUMA node, in which case the
instance must be split across these nodes.
