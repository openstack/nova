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
a way to use Xen hypervisor resource pools, but has been generalized to provide
a mechanism to allow administrators to assign key-value pairs to groups of
machines.  Each node can have multiple aggregates, each aggregate can have
multiple key-value pairs, and the same key-value pair can be assigned to
multiple aggregate.  This information can be used in the scheduler to enable
advanced scheduling, to set up xen hypervisor resources pools or to define
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
  ``default_availability_zone``)

.. warning:: That last rule can be very error-prone. Since the user can see the
  list of availability zones, they have no way to know whether the default
  availability zone name (currently *nova*) is provided because an host
  belongs to an aggregate whose AZ metadata key is set to *nova*, or because
  there are at least one host belonging to no aggregate. Consequently, it is
  highly recommended for users to never ever ask for booting an instance by
  specifying an explicit AZ named *nova* and for operators to never set the
  AZ metadata for an aggregate to *nova*. That leads to some problems
  due to the fact that the instance AZ information is explicitly attached to
  *nova* which could break further move operations when either the host is
  moved to another aggregate or when the user would like to migrate the
  instance.

.. note:: Availablity zone name must NOT contain ':' since it is used by admin
  users to specify hosts where instances are launched in server creation.
  See :doc:`Select hosts where instances are launched </admin/availability-zones>` for more detail.

Xen Pool Host Aggregates
------------------------
Originally all aggregates were Xen resource pools, now an aggregate can be set up as a resource pool by giving the aggregate the correct key-value pair.

You can use aggregates for XenServer resource pools when you have multiple compute nodes installed (only XenServer/XCP via xenapi driver is currently supported), and you want to leverage the capabilities of the underlying hypervisor resource pools. For example, you want to enable VM live migration (i.e. VM migration within the pool) or enable host maintenance with zero-downtime for guest instances. Please, note that VM migration across pools (i.e. storage migration) is not yet supported in XenServer/XCP, but will be added when available. Bear in mind that the two migration techniques are not mutually exclusive and can be used in combination for a higher level of flexibility in your cloud management.

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

    * It has been depricated since microversion 2.43. Use `list hypervisors` instead.
  * start host maintenance (or evacuate-host): disallow a host to serve API requests and migrate instances to other hosts of the aggregate

    * It has been depricated since microversion 2.43. Use `disable service` instead.
  * stop host maintenance: (or rebalance-host): put the host back into operational mode, migrating instances back onto that host

    * It has been depricated since microversion 2.43. Use `enable service` instead.

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
