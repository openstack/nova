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


Nova Concepts and Introduction
==============================


Introduction
------------

Nova is the software that controls your Infrastructure as as Service (IaaS)
cloud computing platform.  It is similar in scope to Amazon EC2 and Rackspace
CloudServers.  Nova does not include any virtualization software, rather it
defines drivers that interact with underlying virtualization mechanisms that
run on your host operating system, and exposes functionality over a web API.

This document does not attempt to explain fundamental concepts of cloud
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

More information about RBAC can be found in the :ref:`auth`.

Concept: API
------------

* EC2
* OpenStack / Rackspace


Concept: Networking
-------------------

Nova has a concept of Fixed Ips and Floating ips.  Fixed ips are assigned to an instance on creation and stay the same until the instance is explicitly terminated.  Floating ips are ip addresses that can be dynamically associated with an instance.  This address can be disassociated and associated with another instance at any time.

There are multiple strategies available for implementing fixed ips:

Flat Mode
~~~~~~~~~

The simplest networking mode.  Each instance receives a fixed ip from the pool.  All instances are attached to the same bridge (br100) by default.  The bridge must be configured manually.  The networking configuration is injected into the instance before it is booted.  Note that this currently only works on linux-style systems that keep networking configuration in /etc/network/interfaces.

Flat DHCP Mode
~~~~~~~~~~~~~~

This is similar to the flat mode, in that all instances are attached to the same bridge.  In this mode nova does a bit more configuration, it will attempt to bridge into an ethernet device (eth0 by default).  It will also run dnsmasq as a dhcpserver listening on this bridge.  Instances receive their fixed ips by doing a dhcpdiscover.

VLAN DHCP Mode
~~~~~~~~~~~~~~

This is the default networking mode and supports the most features.  For multiple machine installation, it requires a switch that supports host-managed vlan tagging.  In this mode, nova will create a vlan and bridge for each project.  The project gets a range of private ips that are only accessible from inside the vlan.  In order for a user to access the instances in their project, a special vpn instance (code named :ref:`cloudpipe <cloudpipe>`) needs to be created.  Nova generates a certificate and key for the user to access the vpn and starts the vpn automatically. More information on cloudpipe can be found :ref:`here <cloudpipe>`.

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
administration and ongoing maintenance of nova, such as user creation,
vpn management, and much more.

See doc:`nova.manage` in the Administration Guide for more details.


Concept: Flags
--------------

python-gflags


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

Nova utilizes the RabbitMQ implementation of the AMQP messaging standard for performing communication between the various nova services.  This message queuing service is used for both local and remote communication because Nova is designed so that there is no requirement that any of the services exist on the same physical machine.  RabbitMQ in particular is very robust and provides the efficiency and reliability that Nova needs.  More information about RabbitMQ can be found at http://www.rabbitmq.com/. 

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

Security groups


Concept: Certificate Authority
------------------------------

Nova does a small amount of certificate management.  These certificates are used for :ref:`project vpns <cloudpipe>` and decrypting bundled images.


Concept: Images
---------------

* launching
* bundling
