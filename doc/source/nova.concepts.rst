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


Nova Concepts and Introduction
==============================


Introduction
------------

Nova, also known as OpenStack Compute, is the software that controls your Infrastructure as as Service (IaaS)
cloud computing platform.  It is similar in scope to Amazon EC2 and Rackspace
Cloud Servers.  Nova does not include any virtualization software, rather it
defines drivers that interact with underlying virtualization mechanisms that
run on your host operating system, and exposes functionality over a web API.

This site does not attempt to explain fundamental concepts of cloud
computing, IaaS, virtualization, or other related technologies.  Instead, it
focuses on describing how Nova's implementation of those concepts is achieved.

This page outlines concepts that you will need to understand as a user or
administrator of an OpenStack installation.  Each section links to more more
detailed information in the :doc:`adminguide/index`,
but you'll probably want to read this section straight-through before tackling
the specifics presented in the administration guide.


Concept: Users and Projects
---------------------------

* access to images is limited by project
* access/secret are per user
* keypairs are per user
* quotas are per project


Concept: Virtualization
-----------------------

* KVM
* UML
* XEN
* HyperV
* qemu


Concept: Instances
------------------

An 'instance' is a word for a virtual machine that runs inside the cloud.

Concept: Instance Type
----------------------

An 'instance type' describes the compute, memory and storage capacity of nova computing instances. In layman terms, this is the size (in terms of vCPUs, RAM, etc.) of the virtual server that you will be launching.

Concept: System Architecture
----------------------------

Nova consists of seven main components, with the Cloud Controller component representing the global state and interacting with all other components. API Server acts as the Web services front end for the cloud controller. Compute Controller provides compute server resources, and the Object Store component provides storage services. Auth Manager provides authentication and authorization services. Volume Controller provides fast and permanent block-level storage for the comput servers. Network Controller provides virtual networks to enable compute servers to interact with each other and with the public network. Scheduler selects the most suitable compute controller to host an instance.

    .. image:: images/Novadiagram.png 

Nova is built on a shared-nothing, messaging-based architecture. All of the major components, that is Compute Controller, Volume Controller, Network Controller, and Object Store can be run on multiple servers. Cloud Controller communicates with Object Store via HTTP (Hyper Text Transfer Protocol), but it communicates with Scheduler, Network Controller, and Volume Controller via AMQP (Advanced Message Queue Protocol). To avoid blocking each component while waiting for a response, Nova uses asynchronous calls, with a call-back that gets triggered when a response is received.

To achieve the shared-nothing property with multiple copies of the same component, Nova keeps all the cloud system state in a distributed data store. Updates to system state are written into this store, using atomic transactions when required. Requests for system state are read out of this store. In limited cases, the read results are cached within controllers for short periods of time (for example, the current list of system users.) 

    .. note:: The database schema is available on the `OpenStack Wiki <http://wiki.openstack.org/NovaDatabaseSchema>`_. 

Concept: Storage
----------------

Volumes
~~~~~~~

A 'volume' is a detachable block storage device.  You can think of it as a usb hard drive.  It can only be attached to one instance at a time, so it does not work like a SAN. If you wish to expose the same volume to multiple instances, you will have to use an NFS or SAMBA share from an existing instance.

Local Storage
~~~~~~~~~~~~~

Every instance larger than m1.tiny starts with some local storage (up to 160GB for m1.xlarge).  This storage is currently the second partition on the root drive.

Concept: Quotas
---------------

Nova supports per-project quotas.  There are currently quotas for number of instances, total number of cores, number of volumes, total number of gigabytes, and number of floating ips.


Concept: RBAC
-------------

Nova provides roles based access control (RBAC) for access to api commands.  A user can have a number of different :ref:`roles <auth_roles>`.  Roles define which api_commands a user can perform.

It is important to know that there are user-specific (sometimes called global) roles and project-specific roles.  A user's actual permissions in a particular project are the INTERSECTION of his user-specific roles and is project-specific roles.

For example: A user can access api commands allowed to the netadmin role (like allocate_address) only if he has the user-specific netadmin role AND the project-specific netadmin role.

More information about RBAC can be found in :ref:`auth`.

Concept: API
------------

* EC2
* OpenStack / Rackspace


Concept: Networking
-------------------

Nova has a concept of Fixed IPs and Floating IPs.  Fixed IPs are assigned to an instance on creation and stay the same until the instance is explicitly terminated.  Floating ips are ip addresses that can be dynamically associated with an instance.  This address can be disassociated and associated with another instance at any time.

There are multiple strategies available for implementing fixed IPs:

Flat Mode
~~~~~~~~~

The simplest networking mode.  Each instance receives a fixed ip from the pool.  All instances are attached to the same bridge (br100) by default.  The bridge must be configured manually.  The networking configuration is injected into the instance before it is booted.  Note that this currently only works on linux-style systems that keep networking configuration in /etc/network/interfaces.

Flat DHCP Mode
~~~~~~~~~~~~~~

This is similar to the flat mode, in that all instances are attached to the same bridge.  In this mode Nova does a bit more configuration, it will attempt to bridge into an ethernet device (eth0 by default).  It will also run dnsmasq as a dhcpserver listening on this bridge.  Instances receive their fixed IPs by doing a dhcpdiscover.

VLAN DHCP Mode
~~~~~~~~~~~~~~

This is the default networking mode and supports the most features.  For multiple machine installation, it requires a switch that supports host-managed vlan tagging.  In this mode, Nova will create a vlan and bridge for each project.  The project gets a range of private ips that are only accessible from inside the vlan.  In order for a user to access the instances in their project, a special vpn instance (code named :ref:`cloudpipe <cloudpipe>`) needs to be created.  Nova generates a certificate and key for the user to access the vpn and starts the vpn automatically. More information on cloudpipe can be found :ref:`here <cloudpipe>`.

The following diagram illustrates how the communication that occurs between the vlan (the dashed box) and the public internet (represented by the two clouds)

.. image:: /images/cloudpipe.png
   :width: 100%

..

Concept: Binaries
-----------------

Nova is implemented by a number of related binaries.  These binaries can run on the same machine or many machines.  A detailed description of each binary is given in the :ref:`binaries section <binaries>` of the developer guide.

.. _manage_usage:

Concept: nova-manage
--------------------

The nova-manage command is used to perform many essential functions for
administration and ongoing maintenance of Nova, such as user creation,
vpn management, and much more.

See :doc:`nova.manage` in the Administration Guide for more details.

Concept: Flags
--------------

Nova uses python-gflags for a distributed command line system, and the flags can either be set when running a command at the command line or within a flag file. When you install Nova packages for the Austin release, each nova service gets its own flag file. For example, nova-network.conf is used for configuring the nova-network service, and so forth. In releases beyond Austin which was released in October 2010, all flags are set in nova.conf.  

Concept: Plugins
----------------

* Managers/Drivers: utils.import_object from string flag
* virt/connections: conditional loading from string flag
* db: LazyPluggable via string flag
* auth_manager: utils.import_class based on string flag
* Volumes: moving to pluggable driver instead of manager
* Network: pluggable managers
* Compute: same driver used, but pluggable at connection


Concept: IPC/RPC
----------------

Nova utilizes the RabbitMQ implementation of the AMQP messaging standard for performing communication between the various Nova services.  This message queuing service is used for both local and remote communication because Nova is designed so that there is no requirement that any of the services exist on the same physical machine.  RabbitMQ in particular is very robust and provides the efficiency and reliability that Nova needs.  More information about RabbitMQ can be found at http://www.rabbitmq.com/. 

Concept: Fakes
--------------

* auth
* ldap


Concept: Scheduler
------------------

* simple
* random


Concept: Security Groups
------------------------

In Nova, a security group is a named collection of network access rules, like firewall policies. These access rules specify which incoming network traffic should be delivered to all VM instances in the group, all other incoming traffic being discarded. Users can modify rules for a group at any time. The new rules are automatically enforced for all running instances and instances launched from then on.

When launching VM instances, the project manager specifies which security groups it wants to join. It will become a member of these specified security groups when it is launched. If no groups are specified, the instances is assigned to the default group, which by default allows all network traffic from other members of this group and discards traffic from other IP addresses and groups. If this does not meet a user's needs, the user can modify the rule settings of the default group.

A security group can be thought of as a security profile or a security role - it promotes the good practice of managing firewalls by role, not by machine. For example, a user could stipulate that servers with the "webapp" role must be able to connect to servers with the "mysql" role on port 3306. Going further with the security profile analogy, an instance can be launched with membership of multiple security groups - similar to a server with multiple roles. Because all rules in security groups are ACCEPT rules, it's trivial to combine them.

Each rule in a security group must specify the source of packets to be allowed, which can either be a subnet anywhere on the Internet (in CIDR notation, with 0.0.0./0 representing the entire Internet) or another security group. In the latter case, the source security group can be any user's group. This makes it easy to grant selective access to one user's instances from instances run by the user's friends, partners, and vendors. 

The creation of rules with other security groups specified as sources helps users deal with dynamic IP addressing. Without this feature, the user would have had to adjust the security groups each time a new instance is launched. This practice would become cumbersome if an application running in Nova is very dynamic and elastic, for example scales up or down frequently.

Security groups for a VM are passed at launch time by the cloud controller to the compute node, and applied at the compute node when a VM is started.

Concept: Certificate Authority
------------------------------

Nova does a small amount of certificate management.  These certificates are used for :ref:`project vpns <cloudpipe>` and decrypting bundled images.


Concept: Images
---------------

* launching
* bundling
