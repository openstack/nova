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

Running Nova on Multiple Nodes
==============================

When you move beyond evaluating the technology and into building an actual
production environemnt, you will need to know how to configure your datacenter
and how to deploy components across your clusters.  This guide should help you
through that process.

Bare-metal Provisioning
-----------------------

To install the base operating system you can use PXE booting.

Types of Hosts
--------------

A single machine in your cluster can act as one or more of the following types
of host:

Nova Services

* Network
* Compute
* Volume
* API
* Objectstore

Other supporting services

* Message Queue
* Database (optional)
* Authentication database (optional)

Initial Setup
-------------

* Networking
* Cloudadmin User Creation

Deployment Technologies
-----------------------

Once you have machines with a base operating system installation, you can deploy
code and configuration with your favorite tools to specify which machines in
your cluster have which roles:

* Puppet
* Chef
