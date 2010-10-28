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


.. _manage_usage:

Concept: nova-manage
--------------------

Introduction
^^^^^^^^^^^^

The nova-manage command is used to perform many essential functions for
administration and ongoing maintenance of nova, such as user creation,
vpn management, and much more.

The standard pattern for executing a nova-manage command is:

``nova-manage <command> <subcommand> [<args>]``

For example, to obtain a list of all projects:

``nova-manage project list``

User Maintenance
^^^^^^^^^^^^^^^^

* user admin: creates a new admin and prints exports
    * arguments: name [access] [secret]
* user create: creates a new user and prints exports
    * arguments: name [access] [secret]
* user delete: deletes an existing user
    * arguments: name
* user exports: prints access and secrets for user in export format
    * arguments: name
* user list: lists all users
    * arguments: none
* user modify: update a users keys & admin flag
    *  arguments: accesskey secretkey admin
    *  leave any field blank to ignore it, admin should be 'T', 'F', or blank

Project Maintenance
^^^^^^^^^^^^^^^^^^^

* project add: Adds user to project
    * arguments: project user
* project create: Creates a new project
    * arguments: name project_manager [description]
* project delete: Deletes an existing project
    * arguments: project_id
* project environment: Exports environment variables to an sourcable file
    * arguments: project_id user_id [filename='novarc]
* project list: lists all projects
    * arguments: none
* project quota: Set or display quotas for project
    * arguments: project_id [key] [value]
* project remove: Removes user from project
    * arguments: project user
* project scrub: Deletes data associated with project
    * arguments: project
* project zipfile: Exports credentials for project to a zip file
    * arguments: project_id user_id [filename='nova.zip]

User Role Management
^^^^^^^^^^^^^^^^^^^^

* role add: adds role to user
    * if project is specified, adds project specific role
    * arguments: user, role [project]
* role has: checks to see if user has role
    * if project is specified, returns True if user has
      the global role and the project role
    * arguments: user, role [project]
* role remove: removes role from user
    * if project is specified, removes project specific role
    * arguments: user, role [project]


Nova Shell
^^^^^^^^^^

* shell bpython
    * start a new bpython shell
* shell ipython
    * start a new ipython shell
* shell python
    * start a new python shell
* shell run
    * ???
* shell script: Runs the script from the specifed path with flags set properly.
    * arguments: path

VPN Management
^^^^^^^^^^^^^^

* vpn list: Print a listing of the VPNs for all projects.
    * arguments: none
* vpn run: Start the VPN for a given project.
    * arguments: project
* vpn spawn: Run all VPNs.
    * arguments: none


Floating IP Management
^^^^^^^^^^^^^^^^^^^^^^

* floating create: Creates floating ips for host by range
    * arguments: host ip_range
* floating delete: Deletes floating ips by range
    * arguments: range
* floating list: Prints a listing of all floating ips
    * arguments: none

Network Management
^^^^^^^^^^^^^^^^^^

* network create: Creates fixed ips for host by range
    * arguments: [fixed_range=FLAG], [num_networks=FLAG],
                 [network_size=FLAG], [vlan_start=FLAG],
                 [vpn_start=FLAG]


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
