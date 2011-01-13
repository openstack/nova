..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Networking
==========

.. todo:: 

    * document hardware specific commands (maybe in admin guide?) (todd)
    * document a map between flags and managers/backends (todd)


The :mod:`nova.network.manager` Module
--------------------------------------

.. automodule:: nova.network.manager
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`nova.network.linux_net` Driver
----------------------------------------

.. automodule:: nova.network.linux_net
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

Tests
-----

The :mod:`network_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.network_unittest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


Legacy docs
-----------

The nova networking components manage private networks, public IP addressing, VPN connectivity, and firewall rules.

Components
----------
There are several key components:

* NetworkController (Manages address and vlan allocation)
* RoutingNode (NATs public IPs to private IPs, and enforces firewall rules)
* AddressingNode (runs DHCP services for private networks)
* BridgingNode (a subclass of the basic nova ComputeNode)
* TunnelingNode (provides VPN connectivity)

Component Diagram
-----------------

Overview::

                                (PUBLIC INTERNET)
                                 |              \
                                / \             / \
                  [RoutingNode] ... [RN]    [TunnelingNode] ... [TN]
                        |             \    /       |              |
                        |            < AMQP >      |              |
 [AddressingNode]--  (VLAN) ...         |        (VLAN)...    (VLAN)      --- [AddressingNode]
                        \               |           \           /
                       / \             / \         / \         / \
                        [BridgingNode] ...          [BridgingNode]


                  [NetworkController]   ...    [NetworkController]
                                    \          /
                                      < AMQP >
                                         |
                                        / \
                       [CloudController]...[CloudController]

While this diagram may not make this entirely clear, nodes and controllers communicate exclusively across the message bus (AMQP, currently).

State Model
-----------
Network State consists of the following facts:

* VLAN assignment (to a project)
* Private Subnet assignment (to a security group) in a VLAN
* Private IP assignments (to running instances)
* Public IP allocations (to a project)
* Public IP associations (to a private IP / running instance)

While copies of this state exist in many places (expressed in IPTables rule chains, DHCP hosts files, etc), the controllers rely only on the distributed "fact engine" for state, queried over RPC (currently AMQP).  The NetworkController inserts most records into this datastore (allocating addresses, etc) - however, individual nodes update state e.g. when running instances crash.

The Public Traffic Path
-----------------------

Public Traffic::

                (PUBLIC INTERNET)
                       |
                     <NAT>  <-- [RoutingNode]
                       |
 [AddressingNode] -->  |
                    ( VLAN )
                       |    <-- [BridgingNode]
                       |
                <RUNNING INSTANCE>

The RoutingNode is currently implemented using IPTables rules, which implement both NATing of public IP addresses, and the appropriate firewall chains. We are also looking at using Netomata / Clusto to manage NATting within a switch or router, and/or to manage firewall rules within a hardware firewall appliance.

Similarly, the AddressingNode currently manages running DNSMasq instances for DHCP services. However, we could run an internal DHCP server (using Scapy ala Clusto), or even switch to static addressing by inserting the private address into the disk image the same way we insert the SSH keys. (See compute for more details).
