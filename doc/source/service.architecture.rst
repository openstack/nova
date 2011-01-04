..
      Copyright 2010-2011 OpenStack LLC

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

Service Architecture
====================

Nova’s Cloud Fabric is composed of the following major components:

* API Server
* Message Queue
* Compute Worker
* Network Controller
* Volume Worker
* Scheduler
* Image Store


.. image:: /images/fabric.png
   :width: 790

API Server 
--------------------------------------------------
At the heart of the cloud framework is an API Server.  This API Server makes command and control of the hypervisor, storage, and networking programmatically available to users in realization of the definition of cloud computing.

The API endpoints are basic http web services which handle authentication, authorization, and basic command and control functions using various API interfaces under the Amazon, Rackspace, and related models.  This enables API compatibility with multiple existing tool sets created for interaction with offerings from other vendors.  This broad compatibility prevents vendor lock-in.

Message Queue
--------------------------------------------------
A messaging queue brokers the interaction between compute nodes (processing), volumes (block storage), the networking controllers (software which controls network infrastructure), API endpoints, the scheduler (determines which physical hardware to allocate to a virtual resource), and similar components.  Communication to and from the cloud controller is by HTTP requests through multiple API endpoints.

A typical message passing event begins with the API server receiving a request from a user.  The API server authenticates the user and ensures that the user is permitted to issue the subject command.  Availability of objects implicated in the request is evaluated and, if available, the request is routed to the queuing engine for the relevant workers.  Workers continually listen to the queue based on their role, and occasionally their type hostname.  When such listening produces a work request, the worker takes assignment of the task and begins its execution.  Upon completion, a response is dispatched to the queue which is received by the API server and relayed to the originating user.  Database entries are queried, added, or removed as necessary throughout the process.

Compute Worker
--------------------------------------------------
Compute workers manage computing instances on host machines.  Through the API, commands are dispatched to compute workers to:

* Run instances
* Terminate instances
* Reboot instances
* Attach volumes
* Detach volumes
* Get console output

Network Controller
--------------------------------------------------
The Network Controller manages the networking resources on host machines.  The API server dispatches commands through the message queue, which are subsequently processed by Network Controllers.  Specific operations include:

* Allocate Fixed IP Addresses
* Configuring VLANs for projects
* Configuring networks for compute nodes

Volume Workers
--------------------------------------------------
Volume Workers interact with iSCSI storage to manage LVM-based instance volumes.  Specific functions include:

* Create Volumes
* Delete Volumes
* Establish Compute volumes

Volumes may easily be transferred between instances, but may be attached to only a single instance at a time.


.. todo:: P2: image store description
