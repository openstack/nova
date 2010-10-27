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

Projects


Concept: Virtualization
-----------------------

* KVM
* UML
* XEN
* HyperV


Concept: Volumes
----------------

Volumes


Concept: Quotas
---------------

* Defaults
* Override for project


Concept: API
------------

* EC2
* OpenStack / Rackspace


Concept: Networking
-------------------

* Simple networking
* VLAN Networking


Concept: Services
-----------------

Services


Concept: Flags
--------------

python-gflags


Concept: Plugins
----------------

LazyPluggable


Concept: IPC/RPC
----------------

Rabbit!


Concept: Fakes
--------------

Fakes


Concept: Scheduler
------------------

Scheduler


Concept: ORM
------------

ORM


Concept: Manager Pattern
------------------------

Managers


Concept: Security Groups
------------------------

Security groups
