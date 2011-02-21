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


Flat Network Mode (Original and Flat)
=====================================

Flat network mode removes most of the complexity of VLAN mode by simply
bridging all instance interfaces onto a single network.

There are two variations of flat mode that differ mostly in how IP addresses
are given to instances.


Original Flat Mode
------------------
IP addresses for VM instances are grabbed from a subnet specified by the network administrator, and injected into the image on launch. All instances of the system are attached to the same Linux networking bridge, configured manually by the network administrator both on the network controller hosting the network and on the computer controllers hosting the instances.  To recap:

* Each compute host creates a single bridge for all instances to use to attach to the external network.
* The networking configuration is injected into the instance before it is booted or it is obtained by a guest agent installed in the instance.
 
Note that the configuration injection currently only works on linux-style systems that keep networking 
configuration in /etc/network/interfaces.


Flat DHCP Mode
--------------
IP addresses for VM instances are grabbed from a subnet specified by the network administrator. Similar to the flat network, a single Linux networking bridge is created and configured manually by the network administrator and used for all instances. A DHCP server is started to pass out IP addresses to VM instances from the specified subnet.  To recap:

* Like flat mode, all instances are attached to a single bridge on the compute node.
* In addition a DHCP server is running to configure instances.

Implementation
--------------

The network nodes do not act as a default gateway in flat mode.  Instances
are given public IP addresses.

Compute nodes have iptables/ebtables entries created per project and
instance to protect against IP/MAC address spoofing and ARP poisoning.


Examples
--------

.. todo:: add flat network mode configuration examples
