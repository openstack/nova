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

Zones
=====

A Nova deployment is called a Zone. A Zone allows you to partition your deployments into logical groups for load balancing and instance distribution. At the very least a Zone requires an API node, a Scheduler node, a database and RabbitMQ. Pushed further a Zone may contain many API nodes, many Scheduler, Volume, Network and Compute nodes as well as a cluster of databases and RabbitMQ servers. 

The idea behind Zones is, if a particular deployment is not capable of servicing a particular request, the request may be forwarded to (child) Zones for possible processing. Zones may be nested in a tree fashion. 

Zones only know about their immediate children, they do not know about their parent Zones and may in fact have more than one parent. Likewise, a Zone's children may themselves have child Zones and, in those cases, the grandchild's internal structure would not be known to the grand-parent. 

Zones share nothing. They communicate via the public OpenStack API only. No database, queue, user or project definition is shared between Zones. 


Capabilities
------------
Routing between Zones is based on the Capabilities of that Zone. Capabilities are nothing more than key/value pairs. Values are multi-value, with each value separated with a semicolon (`;`). When expressed as a string they take the form:

::

  key=value;value;value, key=value;value;value

Zones have Capabilities which are general to the Zone and are set via `--zone_capabilities` flag. Zones also have dynamic per-service Capabilities. Services derived from `nova.manager.SchedulerDependentManager` (such as Compute, Volume and Network) can set these capabilities by calling the `update_service_capabilities()` method on their `Manager` base class. These capabilities will be periodically sent to the Scheduler service automatically. The rate at which these updates are sent is controlled by the `--periodic_interval` flag.

Flow within a Zone
------------------
The brunt of the work within a Zone is done in the Scheduler Service. The Scheduler is responsible for:
- collecting capability messages from the Compute, Volume and Network nodes,
- polling the child Zones for their status and
- providing data to the Distributed Scheduler for performing load balancing calculations

Inter-service communication within a Zone is done with RabbitMQ. Each class of Service (Compute, Volume and Network) has both a named message exchange (particular to that host) and a general message exchange (particular to that class of service). Messages sent to these exchanges are picked off in round-robin fashion. Zones introduce a new fan-out exchange per service. Messages sent to the fan-out exchange are picked up by all services of a particular class. This fan-out exchange is used by the Scheduler services to receive capability messages from the Compute, Volume and Network nodes.

These capability messages are received by the Scheduler services and stored in the `ZoneManager` object. The SchedulerManager object has a reference to the `ZoneManager` it can use for load balancing.

The `ZoneManager` also polls the child Zones periodically to gather their capabilities to aid in decision making. This is done via the OpenStack API `/v1.0/zones/info` REST call. This also captures the name of each child Zone. The Zone name is set via the `--zone_name` flag (and defaults to "nova"). 

Zone administrative functions
-----------------------------
Zone administrative operations are usually done using python-novaclient_

.. _python-novaclient: https://github.com/rackspace/python-novaclient

In order to use the Zone operations, be sure to enable administrator operations in OpenStack API by setting the `--allow_admin_api=true` flag.

Finally you need to enable Zone Forwarding. This will be used by the Distributed Scheduler initiative currently underway. Set `--enable_zone_routing=true` to enable this feature.

Find out about this Zone
------------------------
In any Zone you can find the Zone's name and capabilities with the ``nova zone-info`` command.

::

  alice@novadev:~$ nova zone-info
  +-----------------+---------------+
  |     Property    |     Value     |
  +-----------------+---------------+
  | compute_cpu     | 0.7,0.7       |
  | compute_disk    | 123000,123000 |
  | compute_network | 800,800       |
  | hypervisor      | xenserver     |
  | name            | nova          |
  | network_cpu     | 0.7,0.7       |
  | network_disk    | 123000,123000 |
  | network_network | 800,800       |
  | os              | linux         |
  +-----------------+---------------+

This equates to a GET operation on `.../zones/info`. If you have no child Zones defined you'll usually only get back the default `name`, `hypervisor` and `os` capabilities. Otherwise you'll get back a tuple of min, max values for each capabilities of all the hosts of all the services running in the child zone. These take the `<service>_<capability> = <min>,<max>` format.

Adding a child Zone
-------------------
Any Zone can be a parent Zone. Children are associated to a Zone. The Zone where this command originates from is known as the Parent Zone. Routing is only ever conducted from a Zone to its children, never the other direction. From a parent zone you can add a child zone with the following command:

::

  nova zone-add <child zone api url> <username> <nova api key>

You can get the `child zone api url`, `nova api key` and `username` from the `novarc` file in the child zone. For example:

::

  export NOVA_API_KEY="3bd1af06-6435-4e23-a827-413b2eb86934"
  export NOVA_USERNAME="alice"
  export NOVA_URL="http://192.168.2.120:8774/v1.0/"


This equates to a POST operation to `.../zones/` to add a new zone. No connection attempt to the child zone is done with this command. It only puts an entry in the db at this point. After about 30 seconds the `ZoneManager` in the Scheduler services will attempt to talk to the child zone and get its information. 

Getting a list of child Zones
-----------------------------

::

  nova zone-list

  alice@novadev:~$ nova zone-list
  +----+-------+-----------+--------------------------------------------+---------------------------------+
  | ID |  Name | Is Active |                Capabilities                |             API URL             |
  +----+-------+-----------+--------------------------------------------+---------------------------------+
  | 2  | zone1 | True      | hypervisor=xenserver;kvm, os=linux;windows | http://192.168.2.108:8774/v1.0/ |
  | 3  | zone2 | True      | hypervisor=xenserver;kvm, os=linux;windows | http://192.168.2.115:8774/v1.0/ |
  +----+-------+-----------+--------------------------------------------+---------------------------------+

This equates to a GET operation to `.../zones`.

Removing a child Zone
---------------------
::

  nova zone-delete <N>

This equates to a DELETE call to `.../zones/N`. The Zone with ID=N will be removed. This will only remove the zone entry from the current (parent) Zone, no child Zones are affected. Removing a Child Zone doesn't affect any other part of the hierarchy.
