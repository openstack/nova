..
      Copyright 2010 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      Overview Sections Copyright 2010 Citrix 
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

OpenStack Network Overview
==========================

Introduction
------------

Nova consists of seven main components, with the Cloud Controller component representing the global state and interacting with all other components. API Server acts as the Web services front end for the cloud controller. Compute Controller provides compute server resources, and the Object Store component provides storage services. Auth Manager provides authentication and authorization services. Volume Controller provides fast and permanent block-level storage for the comput servers. Network Controller provides virtual networks to enable compute servers to interact with each other and with the public network. Scheduler selects the most suitable compute controller to host an instance.

.. todo:: Insert Figure 1 image from "An OpenStack Network Overview" contributed by Citrix

Nova is built on a shared-nothing, messaging-based architecture. All of the major components, that is Compute Controller, Volume Controller, Network Controller, and Object Store can be run on multiple servers. Cloud Controller communicates with Object Store via HTTP (Hyper Text Transfer Protocol), but it communicates with Scheduler, Network Controller, and Volume Controller via AMQP (Advanced Message Queue Protocol). To avoid blocking each component while waiting for a response, Nova uses asynchronous calls, with a call-back that gets triggered when a response is received.

To achieve the shared-nothing property with multiple copies of the same component, Nova keeps all the cloud system state in a distributed data store. Updates to system state are written into this store, using atomic transactions when required. Requests for system state are read out of this store. In limited cases, the read results are cached within controllers for short periods of time (for example, the current list of system users.) 

.. note:: The database schema is available on the `OpenStack Wiki <http://wiki.openstack.org/NovaDatabaseSchema>_`. 

Nova Network Strategies
-----------------------

In Nova, users organize their cloud resources in projects. A Nova project consists of a number of VM instances created by a user. For each VM instance, Nova assigns to it a private IP address. (Currently, Nova only supports Linux bridge networking that allows the virtual interfaces to connect to the outside network through the physical interface. Other virtual network technologies, such as Open vSwitch, could be supported in the future.)

Currently, Nova supports three kinds of networks, implemented in three "Network Manager" types respectively: Flat Network Manager, Flat DHCP Network Manager, and VLAN Network Manager. The three kinds of networks can c-exist in a cloud system. However, the scheduler for selecting the type of network for a given project is not yet implemented. Here is a brief description of each of the different network strategies, with a focus on the VLAN Manager in a separate section. 

Flat Network
++++++++++++

IP addresses for VM instances are grabbed from a subnet specified by the network administrator, and injected into the image on launch. All instances of the system are attached to the same Linux networking bridge, configured manually by the network administrator both on the network controller hosting the network and on the computer controllers hosting the instances. 

Flat Network with DHCP
++++++++++++++++++++++

IP addresses for VM instances are grabbed from a subnet specified by the network administrator. Similar to the flat network, a single Linux networking bridge is created and configured manually by the network administrator and used for all instances. A DHCP server is started to pass out IP addresses to VM instances from the specified subnet. 

VLAN Network
++++++++++++

Each project gets its own VLAN, Linux networking bridge, and subnet. The subnets are specified by the network administrator, and are assigned dynamically to a project when required. A DHCP Server is started for each VLAN to pass out IP addresses to VM instances from the subnet assigned to the project. All instances belonging to one project are bridged into the same VLAN for that project. The Linux networking bridges and VLANs are created by Nova when required, described in more detail in Nova VLAN Network Management Implementation. 

Nova VLAN Networks
------------------

Because the flat network and flat DhCP network are simple to understand and yet do not scale well enough for real-world cloud systems, this section focuses on the VLAN network implementation by the VLAN Network Manager. 

In the VLAN network mode, all the VM instances of a project are connected together in a VLAN with the specified private subnet. Each running VM instance is assigned an IP address within the given private subnet. 

.. todo:: Insert Figure 2 from "An OpenStack Network Overview" contributed by Citrix

While network traffic between VM instances belonging to the same VLAN is always open, Nova can enforce isolation of network traffic between different projects by enforcing one VLAN per project. 

In addition, the network administrator can specify a pool of public IP addresses that users may allocate and then assign to VMs, either at boot or dynamically at run-time. This capability is similar to Amazon's 'elastic IPs'. A public IP address may be associated with a running instances, allowing the VM instance to be accessed from the public network. The public IP addresses are accessible from the network host and NATed to the private IP address of the project. 

.. todo:: Describe how a public IP address could be associated with a project (a VLAN)

Nova VLAN Network Management Implementation
-------------------------------------------

This section describes the current (November 2010) implementation of the network structure of Nova.

The network assignment to a project, and IP address assignment to a VM instance, are triggered when a user starts to run a VM instance. When running a VM instance, a user needs to specify a project for the instances, and the security groups (described in Security Groups) when the instance wants to join. If this is the first instance to be created for the project, then Nova (the cloud controller) needs to find a network controller to be the network host for the project; it then sets up a private network by finding an unused VLAN id, an unused subnet, and then the controller assigns them to the project, it also assigns a name to the project's Linux bridge, and allocating a private IP within the project's subnet for the new instance.

If the instance the user wants to start is not the project's first, a subnet and a VLAN must have already been assigned to the project; therefore the system needs only to find an available IP address within the subnet and assign it to the new starting instance. If there is no private IP available within the subnet, an exception will be raised to the cloud controller, and the VM creation cannot proceed.


.. todo:: insert the name of the Linux bridge, is it always named bridge?


Managing Networks
=================

VPN Management
~~~~~~~~~~~~~~

* vpn list: Print a listing of the VPNs for all projects.
    * arguments: none
* vpn run: Start the VPN for a given project.
    * arguments: project
* vpn spawn: Run all VPNs.
    * arguments: none


Floating IP Management
~~~~~~~~~~~~~~~~~~~~~~

* floating create: Creates floating ips for host by range
    * arguments: host ip_range
* floating delete: Deletes floating ips by range
    * arguments: range
* floating list: Prints a listing of all floating ips
    * arguments: none

Network Management
~~~~~~~~~~~~~~~~~~

* network create: Creates fixed ips for host by range
    * arguments: [fixed_range=FLAG], [num_networks=FLAG],
                 [network_size=FLAG], [vlan_start=FLAG],
                 [vpn_start=FLAG]

