MultiNic
========

What is it
----------

Multinic allows an instance to have more than one vif connected to it. Each vif is represenative of a separate network with its own IP block.

Managers
--------

Each of the 3 network managers are designed to run indipendantly of the compute manager. They expose a common API for the compute manager to call to determine and configure the network(s) for an instance. Direct calls to either the network api or especially the DB should be avoided by the virt layers.

Flat Manager 
------------

    .. image:: /images/multinic_flat.png

The flat manager is most similar to a traditional switched network environment. It assumes that the IP routing, DNS, DHCP (possibly) and bridge creation is handled by something else. That is it makes no attemp to configure any of this. It does keep track of a range of IPs for the instances that are connected to the network to be allocated.

Each instance will get a fixed ip from each network's pool. The guest operating system may be configured to gather this information through an agent or by the hypervisor injecting the files, or it may ignore it completly and come up with only a layer 2 connection.

Flat manager requires at least one nova-network process running that will listen to the API queue and respond to queries. It does not need to sit on any of the networks but it does keep track of the ip's it hands out to instances.

FlatDHCP Manager
----------------

    .. image:: /images/multinic_dhcp.png



VLAN Manager
------------
