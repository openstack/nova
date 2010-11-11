..
      Copyright 2010 United States Government as represented by the
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


VLAN Network Mode
=================

VLAN Network Mode is the default mode for Nova.  It provides a private network
segment for each project's instances that can be accessed via a dedicated
VPN connection from the Internet.


Goals
-----

* each project is in a protected network segment

  * RFC-1918 IP space
  * public IP via NAT
  * no default inbound Internet access without public NAT
  * limited (project-admin controllable) outbound Internet access
  * limited (project-admin controllable) access to other project segments
  * all connectivity to instance and cloud API is via VPN into the project segment

* common DMZ segment for support services (only visible from project segment)

  * metadata
  * dashboard


Limitations
-----------

* Projects / cluster limited to available VLANs in switching infrastructure
* Requires VPN for access to project segment


Implementation
--------------

Currently Nova segregates project VLANs using 802.1q VLAN tagging in the 
switching layer.  Compute hosts create VLAN-specific interfaces and bridges 
as required.

The network nodes act as default gateway for project networks and contain 
all of the routing and firewall rules implementing security groups.  The
network node also handles DHCP to provide instance IPs for each project.

VPN access is provided by running a small instance called CloudPipe 
on the IP immediately following the gateway IP for each project.  The
network node maps a dedicated public IP/port to the CloudPipe instance.

Compute nodes have per-VLAN interfaces and bridges created as required.
These do NOT have IP addresses in the host to protect host access.
Compute nodes have iptables/ebtables entries created per project and
instance to protect against IP/MAC address spoofing and ARP poisoning.


External Infrastructure
-----------------------

Nova assumes the following is available:

* DNS
* NTP
* Internet connectivity


Example
-------

This example network configuration demonstrates most of the capabilities
of VLAN Mode.  It splits administrative access to the nodes onto a dedicated
management network and uses dedicated network nodes to handle all
routing and gateway functions.

It uses a 10GB network for instance traffic and a 1GB network for management.


Hardware
~~~~~~~~

* All nodes have a minimum of two NICs for management and production.

  * management is 1GB
  * production is 10GB
  * add additional NICs for bonding or HA/performance

* network nodes should have an additional NIC dedicated to public Internet traffic
* switch needs to support enough simultaneous VLANs for number of projects
* production network configured as 802.1q trunk on switch


Operation
~~~~~~~~~

The network node controls the project network configuration:

* assigns each project a VLAN and private IP range
* starts dnsmasq on project VLAN to serve private IP range
* configures iptables on network node for default project access
* launches CloudPipe instance and configures iptables access

When starting an instance the network node:

* sets up a VLAN interface and bridge on each host as required when an
  instance is started on that host
* assigns private IP to instance
* generates MAC address for instance
* update dnsmasq with IP/MAC for instance

When starting an instance the compute node:

* sets up a VLAN interface and bridge on each host as required when an
  instance is started on that host


Setup
~~~~~

* Assign VLANs in the switch:

  * public Internet segment
  * production network
  * management network
  * cluster DMZ

* Assign a contiguous range of VLANs to Nova for project use.
* Configure management NIC ports as management VLAN access ports.
* Configure management VLAN with Internet access as required
* Configure production NIC ports as 802.1q trunk ports.
* Configure Nova (need to add specifics here)

  * public IPs
  * instance IPs
  * project network size
  * DMZ network

.. todo:: need specific Nova configuration added
