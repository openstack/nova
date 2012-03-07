..
      Copyright 2012 OpenStack, LLC
      Copyright 2012 Citrix Systems, Inc.
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

This extension introduces the concept of aggregate into Nova. Host aggregates are different from zones and availability zones: while the former allows the partition of Nova deployments into logical groups for load balancing and instance distribution, the latter are for providing some form of physical isolation and redundancy from other availability zones (e.g. by using separate power supply and network gears). Availability zones do not necessarily mean geographic distribution whereas zones usually do. Host aggregates can be regarded as a mechanism to further partitioning an availability zone, i.e. into multiple groups of hosts that share common resources like storage and network. This enables a finer level of granularity in which to structure an entire OpenStack deployment. Aggregates allows higher availability of a single guest instance within an availability zone, it enables advanced VM placement strategies, and more importantly it enables hosts' zero-downtime upgrades (for example, via VM live migration across members of the aggregate, thus causing no disruption to guest instances).

You can use this extension when you have multiple Compute nodes installed (only XenServer/XCP via xenapi driver is currently supported), and you want to leverage the capabilities of the underlying hypervisor resource pools. For example, you want to enable VM live migration (i.e. VM migration within the pool) or enable host maintenance with zero-downtime for guest instances. Please, note that VM migration across pools (i.e. storage migration) is not yet supported in XenServer/XCP, but will be added when available. Bear in mind that the two migration techniques are not mutually exclusive and can be used in combination for a higher level of flexibility in your cloud management.

Design
=======

The OSAPI Admin API will be extended to support the following operations:

    * Aggregates

      * list aggregates: returns a list of all the host-aggregates (optionally filtered by availability zone)
      * create aggregate: creates an aggregate, takes a friendly name, etc. returns an id
      * show aggregate: shows the details of an aggregate (id, name, availability_zone, hosts and metadata)
      * update aggregate: updates the name and availability zone of an aggregate
      * set metadata: sets the metadata on an aggregate to the values supplied
      * delete aggregate: deletes an aggregate, it fails if the aggregate is not empty
      * add host: adds a host to the aggregate
      * remove host: removes a host from the aggregate, it fails if the host is not disabled or

    * Hosts

      * start host maintenance (or evacuate-host): disallow a host to serve API requests and migrate instances to other hosts of the aggregate
      * stop host maintenance: (or rebalance-host): put the host back into operational mode, migrating instances back onto that host

Using the Nova CLI
==================

Using the nova command you can create, delete and manage aggregates. The following section outlines the list of available commands.

Usage
-----

::

  * aggregate-list                                                    Print a list of all aggregates.
  * aggregate-create         <name> <availability_zone>               Create a new aggregate with the specified details.
  * aggregate-delete         <id>                                     Delete the aggregate by its id.
  * aggregate-details        <id>                                     Show details of the specified aggregate.
  * aggregate-add-host       <id> <host>                              Add the host to the specified aggregate.
  * aggregate-remove-host    <id> <host>                              Remove the specified host from the specfied aggregate.
  * aggregate-set-metadata   <id> <key=value> [<key=value> ...]       Update the metadata associated with the aggregate.
  * aggregate-update         <id> <name> [<availability_zone>]        Update the aggregate's name and optionally availablity zone.

  * host-update              --maintenance [enable | disable]         Put/resume host into/from maintenance.
