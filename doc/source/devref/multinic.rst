MultiNic
========

What is it
----------

Multinic allows an instance to have more than one vif connected to it. Each vif is representative of a separate network with its own IP block.

Managers
--------

Each of the network managers are designed to run independently of the compute manager. They expose a common API for the compute manager to call to determine and configure the network(s) for an instance. Direct calls to either the network api or especially the DB should be avoided by the virt layers.

On startup a manager looks in the networks table for networks it is assigned and configures itself to support that network. Using the periodic task, they will claim new networks that have no host set. Only one network per network-host will be claimed at a time. This allows for psuedo-loadbalancing if there are multiple network-hosts running.

Flat Manager 
------------

    .. image:: /images/multinic_flat.png

The Flat manager is most similar to a traditional switched network environment. It assumes that the IP routing, DNS, DHCP (possibly) and bridge creation is handled by something else. That is it makes no attempt to configure any of this. It does keep track of a range of IPs for the instances that are connected to the network to be allocated.

Each instance will get a fixed IP from each network's pool. The guest operating system may be configured to gather this information through an agent or by the hypervisor injecting the files, or it may ignore it completely and come up with only a layer 2 connection.

Flat manager requires at least one nova-network process running that will listen to the API queue and respond to queries. It does not need to sit on any of the networks but it does keep track of the IPs it hands out to instances.

FlatDHCP Manager
----------------

    .. image:: /images/multinic_dhcp.png

FlatDHCP manager builds on the the Flat manager adding dnsmask (DNS and DHCP) and radvd (Router Advertisement) servers on the bridge for that network. The services run on the host that is assigned to that network. The FlatDHCP manager will create its bridge as specified when the network was created on the network-host when the network host starts up or when a new network gets allocated to that host. Compute nodes will also create the bridges as necessary and connect instance VIFs to them.

VLAN Manager
------------

    .. image:: /images/multinic_vlan.png

The VLAN manager sets up forwarding to/from a cloudpipe instance in addition to providing dnsmask (DNS and DHCP) and radvd (Router Advertisement) services for each network. The manager will create its bridge as specified when the network was created on the network-host when the network host starts up or when a new network gets allocated to that host. Compute nodes will also create the bridges as necessary and connect instance VIFs to them.
