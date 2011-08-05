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

Nova System Architecture
========================

Nova is built on a shared-nothing, messaging-based architecture. All of the major nova components can be run on multiple servers. This means that most component to component communication must go via message queue. In order to avoid blocking each component while waiting for a response, we use deferred objects, with a callback that gets triggered when a response is received.

Nova recently moved to using a sql-based central database that is shared by all components in the system.  The amount and depth of the data fits into a sql database quite well.  For small deployments this seems like an optimal solution.  For larger deployments, and especially if security is a concern, nova will be moving towards multiple data stores with some kind of aggregation system.

Components
----------

Below you will find a helpful explanation of the different components.

::

                                      /- ( LDAP )
                  [ Auth Manager ] ---
                          |           \- ( DB )
                          |
                          |       [ scheduler ] - [ volume ]  - ( ATAoE/iSCSI )
                          |                /
  [ Web Dashboard ] -> [ api ] -- < AMQP > ------ [ network ] - ( Flat/Vlan )
                          |                \
                       < HTTP >   [ scheduler ] - [ compute ] - ( libvirt/xen )
                          |                           |
                   [ objectstore ] < - retrieves images

* DB: sql database for data storage. Used by all components (LINKS NOT SHOWN)
* Web Dashboard: potential external component that talks to the api
* api: component that receives http requests, converts commands and communicates with other components via the queue or http (in the case of objectstore)
* Auth Manager: component responsible for users/projects/and roles.  Can backend to DB or LDAP.  This is not a separate binary, but rather a python class that is used by most components in the system.
* objectstore: http server that replicates s3 api and allows storage and retrieval of images
* scheduler: decides which host gets each vm and volume
* volume: manages dynamically attachable block devices.
* network: manages ip forwarding, bridges, and vlans
* compute: manages communication with hypervisor and virtual machines.
