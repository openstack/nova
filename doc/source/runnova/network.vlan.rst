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


VLAN Network Mode
=================
VLAN Network Mode is the default mode for Nova.  It provides a private network
segment for each project's instances that can be accessed via a dedicated
VPN connection from the Internet.

In this mode, each project gets its own VLAN, Linux networking bridge, and subnet. The subnets are specified by the network administrator, and are assigned dynamically to a project when required. A DHCP Server is started for each VLAN to pass out IP addresses to VM instances from the subnet assigned to the project. All instances belonging to one project are bridged into the same VLAN for that project. The Linux networking bridges and VLANs are created by Nova when required, described in more detail in Nova VLAN Network Management Implementation. 

.. 
    (this text revised above)
    Because the flat network and flat DhCP network are simple to understand and yet do not scale well enough for real-world cloud systems, this section focuses on the VLAN network implementation by the VLAN Network Manager. 


    In the VLAN network mode, all the VM instances of a project are connected together in a VLAN with the specified private subnet. Each running VM instance is assigned an IP address within the given private subnet. 

.. image:: /images/Novadiagram.png
   :width: 790
   
While network traffic between VM instances belonging to the same VLAN is always open, Nova can enforce isolation of network traffic between different projects by enforcing one VLAN per project. 

In addition, the network administrator can specify a pool of public IP addresses that users may allocate and then assign to VMs, either at boot or dynamically at run-time. This capability is similar to Amazon's 'elastic IPs'. A public IP address may be associated with a running instances, allowing the VM instance to be accessed from the public network. The public IP addresses are accessible from the network host and NATed to the private IP address of the project. A public IP address could be associated with a project using the euca-allocate-address commands. 

This is the default networking mode and supports the most features.  For multiple machine installation, it requires a switch that supports host-managed vlan tagging.  In this mode, nova will create a vlan and bridge for each project.  The project gets a range of private ips that are only accessible from inside the vlan.  In order for a user to access the instances in their project, a special vpn instance (code named :ref:`cloudpipe <cloudpipe>`) needs to be created.  Nova generates a certificate and key for the user to access the vpn and starts the vpn automatically. More information on cloudpipe can be found :ref:`here <cloudpipe>`.

The following diagram illustrates how the communication that occurs between the vlan (the dashed box) and the public internet (represented by the two clouds)

.. image:: /images/cloudpipe.png
   :width: 100%

Goals
-----

For our implementation of Nova, our goal is that each project is in a protected network segment. Here are the specifications we keep in mind for meeting this goal.

  * RFC-1918 IP space
  * public IP via NAT
  * no default inbound Internet access without public NAT
  * limited (project-admin controllable) outbound Internet access
  * limited (project-admin controllable) access to other project segments
  * all connectivity to instance and cloud API is via VPN into the project segment

We also keep as a goal a common DMZ segment for support services, meaning these items are only visible from project segment:

  * metadata
  * dashboard

Limitations
-----------

We kept in mind some of these limitations: 

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

The network assignment to a project, and IP address assignment to a VM instance, are triggered when a user starts to run a VM instance. When running a VM instance, a user needs to specify a project for the instances, and the security groups (described in Security Groups) when the instance wants to join. If this is the first instance to be created for the project, then Nova (the cloud controller) needs to find a network controller to be the network host for the project; it then sets up a private network by finding an unused VLAN id, an unused subnet, and then the controller assigns them to the project, it also assigns a name to the project's Linux bridge (br100 stored in the Nova database), and allocating a private IP within the project's subnet for the new instance.

If the instance the user wants to start is not the project's first, a subnet and a VLAN must have already been assigned to the project; therefore the system needs only to find an available IP address within the subnet and assign it to the new starting instance. If there is no private IP available within the subnet, an exception will be raised to the cloud controller, and the VM creation cannot proceed.


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

