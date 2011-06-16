MultiNic
========

What is it
----------

Multinic allows an instance to have more than one vif connected to it. Each vif is represenative of a separate network with its own IP block.

<Diagram of virtual machine with 2 vifs & hypervisor with 2 bridges>

Managers
--------

Each of the 3 network managers are designed to run indipendantly of the compute manager. They expose a common API for the compute manager to call to determine and configure the network(s) for an instance. Direct calls to either the network api or especially the DB should be avoided by the virt layers.

Flat Examples
-------------




FlatDHCP Examples
-----------------

VLAN Examples
-------------
