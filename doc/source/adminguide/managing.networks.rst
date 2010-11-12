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

Networking Overview
===================
In Nova, users organize their cloud resources in projects. A Nova project consists of a number of VM instances created by a user. For each VM instance, Nova assigns to it a private IP address. (Currently, Nova only supports Linux bridge networking that allows the virtual interfaces to connect to the outside network through the physical interface. Other virtual network technologies, such as Open vSwitch, could be supported in the future.) The Network Controller provides virtual networks to enable compute servers to interact with each other and with the public network.

..
    (perhaps some of this should be moved elsewhere)
    Introduction
    ------------

    Nova consists of seven main components, with the Cloud Controller component representing the global state and interacting with all other components. API Server acts as the Web services front end for the cloud controller. Compute Controller provides compute server resources, and the Object Store component provides storage services. Auth Manager provides authentication and authorization services. Volume Controller provides fast and permanent block-level storage for the comput servers. Network Controller provides virtual networks to enable compute servers to interact with each other and with the public network. Scheduler selects the most suitable compute controller to host an instance.

    .. todo:: Insert Figure 1 image from "An OpenStack Network Overview" contributed by Citrix

    Nova is built on a shared-nothing, messaging-based architecture. All of the major components, that is Compute Controller, Volume Controller, Network Controller, and Object Store can be run on multiple servers. Cloud Controller communicates with Object Store via HTTP (Hyper Text Transfer Protocol), but it communicates with Scheduler, Network Controller, and Volume Controller via AMQP (Advanced Message Queue Protocol). To avoid blocking each component while waiting for a response, Nova uses asynchronous calls, with a call-back that gets triggered when a response is received.

    To achieve the shared-nothing property with multiple copies of the same component, Nova keeps all the cloud system state in a distributed data store. Updates to system state are written into this store, using atomic transactions when required. Requests for system state are read out of this store. In limited cases, the read results are cached within controllers for short periods of time (for example, the current list of system users.) 

    .. note:: The database schema is available on the `OpenStack Wiki <http://wiki.openstack.org/NovaDatabaseSchema>_`. 

Nova Network Strategies
-----------------------

Currently, Nova supports three kinds of networks, implemented in three "Network Manager" types respectively: Flat Network Manager, Flat DHCP Network Manager, and VLAN Network Manager. The three kinds of networks can c-exist in a cloud system. However, the scheduler for selecting the type of network for a given project is not yet implemented. Here is a brief description of each of the different network strategies, with a focus on the VLAN Manager in a separate section. 

Read more about Nova network strategies here:

.. toctree::
   :maxdepth: 1

   network.flat.rst
   network.vlan.rst


Network Management Commands
---------------------------

Admins and Network Administrators can use the 'nova-manage' command to manage network resources:

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

