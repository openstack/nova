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

Nova is comprised of multiple server processes, each performing different
functions. The user-facing interface is a REST API, while internally Nova
components communicate via an RPC message passing mechanism.

The API servers process REST requests, which typically involve database
reads/writes, optionally sending RPC messages to other Nova services,
and generating responses to the REST calls.
RPC messaging is done via the **oslo.messaging** library,
an abstraction on top of message queues.
Most of the major nova components can be run on multiple servers, and have
a manager that is listening for RPC messages.
The one major exception is ``nova-compute``, where a single process runs on the
hypervisor it is managing (except when using the VMware or Ironic drivers).
The manager also, optionally, has periodic tasks.
For more details on our RPC system, please see: :doc:`/reference/rpc`

Nova also uses a central database that is (logically) shared between all
components. However, to aid upgrade, the DB is accessed through an object
layer that ensures an upgraded control plane can still communicate with
a ``nova-compute`` running the previous release.
To make this possible nova-compute proxies DB requests over RPC to a
central manager called ``nova-conductor``.

To horizontally expand Nova deployments, we have a deployment sharding
concept called cells. For more information please see: :doc:`cells`

Components
----------

Below you will find a helpful explanation of the key components
of a typical Nova deployment.

.. image:: /_static/images/architecture.svg
   :width: 100%

* DB: sql database for data storage.
* API: component that receives HTTP requests, converts commands and communicates with other components via the **oslo.messaging** queue or HTTP.
* Scheduler: decides which host gets each instance.
* Compute: manages communication with hypervisor and virtual machines.
* Conductor: handles requests that need coordination (build/resize), acts as a
  database proxy, or handles object conversions.
* `Placement <https://docs.openstack.org/nova/latest/user/placement.html>`__: tracks resource provider inventories and usages.

While all services are designed to be horizontally scalable, you should have significantly more computes than anything else.
