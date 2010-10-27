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


Concepts and Introduction
=========================


Introduction
------------

Nova is the software that controls your Infrastructure as as Service (IaaS)
cloud computing platform.  It is similar in scope to Amazon EC2 and Rackspace
CloudServers.  Nova does not include any virtualization software, rather it
defines drivers that interact with underlying virtualization mechanisms that
run on your host operating system, and exposes functionality over a web API.

This document does not attempt to explain fundamental concepts of cloud
computing, IaaS, virtualization, or other related technologies.  Instead, it
focues on describing how Nova's implementation of those concepts is achieved.

This page outlines concepts that you will need to understand as a user or
administrator of an OpenStack installation.  Each section links to more more
detailed information in the `Administration Guide`_, but you'll probably want
to read this section straight-through before tackling the specifics presented
in the administration guide.

.. _`Administration Guide`: administration.guide.html


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

Concept: Volumes
----------------

A 'volume' is a detachable block storage device.  You can think of it as a usb hard drive.  It can only be attached to one instance at a time, and it behaves


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
^^^^^^^^^

The simplest networking mode.  Each instance receives a fixed ip from the pool.  All instances are attached to the same bridge (br100) by default.  The bridge must be configured manually.  The networking configuration is injected into the instance before it is booted.  Note that this currently only works on linux-style systems that keep networking configuration in /etc/network/interfaces.

Flat DHCP Mode
^^^^^^^^^^^^^^

This is similar to the flat mode, in that all instances are attached to the same bridge.  In this mode nova does a bit more configuration, it will attempt to bridge into an ethernet device (eth0 by default).  It will also run dnsmasq as a dhcpserver listening on this bridge.  Instances receive their fixed ips by doing a dhcpdiscover.

VLAN DHCP Mode
^^^^^^^^^^^^^^

This is the default networking mode and supports the most features.  For multiple machine installation, it requires a switch that supports host-managed vlan tagging.  In this mode, nova will create a vlan and bridge for each project.  The project gets a range of private ips that are only accessible from inside the vlan.  In order for a user to access the instances in their project, a special vpn instance (code name cloudpipe) needs to be created.  Nova generates a certificate and key for the userto access the vpn and starts the vpn automatically.

The following diagram illustrates how the communication that occurs between the vlan (the dashed box) and the public internet (represented by the two clouds)

.. image:: /images/cloudpipe.png
   :width: 100%

..

Concept: Services
-----------------

* nova-api
* nova-scheduler
* nova-compute
* nova-volume
* nova-network
* nova-instancemonitor


Concept: nova-manage
--------------------

nova-manage is a command line utility for performing administrative tasks and checking on the health of the system.


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

Rabbit!


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

Per-project CA
* Images
* VPNs


Concept: Images
---------------

* launching
* bundling
