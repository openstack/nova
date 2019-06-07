..
      Copyright 2012 OpenStack Foundation
      Copyright 2012 Citrix Systems, Inc.
      Copyright 2012, The Cloudscaling Group, Inc.
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

Host Aggregates
===============

Host aggregates can be regarded as a mechanism to further partition an
availability zone; while availability zones are visible to users, host
aggregates are only visible to administrators.  Host aggregates started out as
a way to use Xen hypervisor resource pools, but have been generalized to provide
a mechanism to allow administrators to assign key-value pairs to groups of
machines.  Each node can have multiple aggregates, each aggregate can have
multiple key-value pairs, and the same key-value pair can be assigned to
multiple aggregates.  This information can be used in the scheduler to enable
advanced scheduling, to set up Xen hypervisor resource pools or to define
logical groups for migration.  For more information, including an example of
associating a group of hosts to a flavor, see :ref:`host-aggregates`.


Availability Zones (AZs)
------------------------

Availability Zones are the end-user visible logical abstraction for
partitioning a cloud without knowing the physical infrastructure.
That abstraction doesn't come up in Nova with an actual database model since
the availability zone is actually a specific metadata information attached to
an aggregate. Adding that specific metadata to an aggregate makes the aggregate
visible from an end-user perspective and consequently allows to schedule upon a
specific set of hosts (the ones belonging to the aggregate).

That said, there are a few rules to know that diverge from an API perspective
between aggregates and availability zones:

- one host can be in multiple aggregates, but it can only be in one
  availability zone
- by default a host is part of a default availability zone even if it doesn't
  belong to an aggregate (the configuration option is named
  :oslo.config:option:`default_availability_zone`)

.. warning:: That last rule can be very error-prone. Since the user can see the
  list of availability zones, they have no way to know whether the default
  availability zone name (currently *nova*) is provided because an host
  belongs to an aggregate whose AZ metadata key is set to *nova*, or because
  there is at least one host not belonging to any aggregate. Consequently, it is
  highly recommended for users to never ever ask for booting an instance by
  specifying an explicit AZ named *nova* and for operators to never set the
  AZ metadata for an aggregate to *nova*. That leads to some problems
  due to the fact that the instance AZ information is explicitly attached to
  *nova* which could break further move operations when either the host is
  moved to another aggregate or when the user would like to migrate the
  instance.

.. note:: Availability zone name must NOT contain ':' since it is used by admin
  users to specify hosts where instances are launched in server creation.
  See :doc:`Select hosts where instances are launched </admin/availability-zones>` for more detail.

There is a nice educational video about availability zones from the Rocky
summit which can be found here: https://www.openstack.org/videos/vancouver-2018/curse-your-bones-availability-zones-1

Implications for moving servers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are several ways to move a server to another host: evacuate, resize,
cold migrate, live migrate, and unshelve. Move operations typically go through
the scheduler to pick the target host *unless* a target host is specified and
the request forces the server to that host by bypassing the scheduler. Only
evacuate and live migrate can forcefully bypass the scheduler and move a
server to a specified host and even then it is highly recommended to *not*
force and bypass the scheduler.

With respect to availability zones, a server is restricted to a zone if:

1. The server was created in a specific zone with the ``POST /servers`` request
   containing the ``availability_zone`` parameter.
2. If the server create request did not contain the ``availability_zone``
   parameter but the API service is configured for
   :oslo.config:option:`default_schedule_zone` then by default the server will
   be scheduled to that zone.
3. The shelved offloaded server was unshelved by specifying the
   ``availability_zone`` with the ``POST /servers/{server_id}/action`` request
   using microversion 2.77 or greater.

If the server was not created in a specific zone then it is free to be moved
to other zones, i.e. the :ref:`AvailabilityZoneFilter <AvailabilityZoneFilter>`
is a no-op.

Knowing this, it is dangerous to force a server to another host with evacuate
or live migrate if the server is restricted to a zone and is then forced to
move to a host in another zone, because that will create an inconsistency in
the internal tracking of where that server should live and may require manually
updating the database for that server. For example, if a user creates a server
in zone A and then the admin force live migrates the server to zone B, and then
the user resizes the server, the scheduler will try to move it back to zone A
which may or may not work, e.g. if the admin deleted or renamed zone A in the
interim.

Resource affinity
~~~~~~~~~~~~~~~~~

The :oslo.config:option:`cinder.cross_az_attach` configuration option can be
used to restrict servers and the volumes attached to servers to the same
availability zone.

A typical use case for setting ``cross_az_attach=False`` is to enforce compute
and block storage affinity, for example in a High Performance Compute cluster.

By default ``cross_az_attach`` is True meaning that the volumes attached to
a server can be in a different availability zone than the server. If set to
False, then when creating a server with pre-existing volumes or attaching a
volume to a server, the server and volume zone must match otherwise the
request will fail. In addition, if the nova-compute service creates the volumes
to attach to the server during server create, it will request that those
volumes are created in the same availability zone as the server, which must
exist in the block storage (cinder) service.

As noted in the `Implications for moving servers`_ section, forcefully moving
a server to another zone could also break affinity with attached volumes.

.. note:: ``cross_az_attach=False`` is not widely used nor tested extensively
    and thus suffers from some known issues:

    * `Bug 1694844 <https://bugs.launchpad.net/nova/+bug/1694844>`_
    * `Bug 1781421 <https://bugs.launchpad.net/nova/+bug/1781421>`_

Design
------

The OSAPI Admin API is extended to support the following operations:

* Aggregates

  * list aggregates: returns a list of all the host-aggregates
  * create aggregate: creates an aggregate, takes a friendly name, etc. returns an id
  * show aggregate: shows the details of an aggregate (id, name, availability_zone, hosts and metadata)
  * update aggregate: updates the name and availability zone of an aggregate
  * set metadata: sets the metadata on an aggregate to the values supplied
  * delete aggregate: deletes an aggregate, it fails if the aggregate is not empty
  * add host: adds a host to the aggregate
  * remove host: removes a host from the aggregate
* Hosts

  * list all hosts by service

    * It has been deprecated since microversion 2.43. Use `list hypervisors` instead.
  * start host maintenance (or evacuate-host): disallow a host to serve API requests and migrate instances to other hosts of the aggregate

    * It has been deprecated since microversion 2.43. Use `disable service` instead.
  * stop host maintenance (or rebalance-host): put the host back into operational mode, migrating instances back onto that host

    * It has been deprecated since microversion 2.43. Use `enable service` instead.

* Hypervisors

  * list hypervisors: list hypervisors with hypervisor hostname

* Compute services

  * enable service
  * disable service

Using the Nova CLI
------------------

Using the nova command you can create, delete and manage aggregates. The following section outlines the list of available commands.

Usage
~~~~~

::

  * aggregate-list                                                    Print a list of all aggregates.
  * aggregate-create         <name> [<availability_zone>]             Create a new aggregate with the specified details.
  * aggregate-delete         <aggregate>                              Delete the aggregate by its ID or name.
  * aggregate-show           <aggregate>                              Show details of the aggregate specified by its ID or name.
  * aggregate-add-host       <aggregate> <host>                       Add the host to the aggregate specified by its ID or name.
  * aggregate-remove-host    <aggregate> <host>                       Remove the specified host from the aggregate specified by its ID or name.
  * aggregate-set-metadata   <aggregate> <key=value> [<key=value> ...]
                                                                      Update the metadata associated with the aggregate specified by its ID or name.
  * aggregate-update         [--name <name>] [--availability-zone <availability-zone>] <aggregate>
                                                                      Update the aggregate's name or availability zone.

  * host-list                                                         List all hosts by service.
  * hypervisor-list          [--matching <hostname>] [--marker <marker>] [--limit <limit>]
                                                                      List hypervisors.

  * host-update              [--status <enable|disable>] [--maintenance <enable|disable>] <hostname>
                                                                      Put/resume host into/from maintenance.
  * service-enable           <id>                                     Enable the service.
  * service-disable          [--reason <reason>] <id>                 Disable the service.
