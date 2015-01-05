..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.


Cells V2 Manifesto
==================

Problem
-------

Nova currently depends on a single logical database and message queue that all
nodes depend on for communication and data persistence. This becomes an issue
for deployers as scaling and providing fault tolerance for these systems is
difficult.

We have an experimental feature in Nova called "cells" which is used by some
large deployments to partition compute nodes into smaller groups, coupled with
a database and queue. This seems to be a well-liked and easy-to-understand
arrangement of resources, but the implementation of it has issues for
maintenance and correctness.

Proposal
--------

Right now, when a request hits the Nova API for a particular instance, the
instance information is fetched from the database, which contains the hostname
of the compute node on which the instance currently lives. If the request needs
to take action on the instance (which is most of them), the hostname is used to
calculate the name of a queue, and a message is written there which finds its
way to the proper compute node.

The meat of this proposal is changing the above hostname lookup into two parts
that yield three pieces of information instead of one. Basically, instead of
merely looking up the *name* of the compute node on which an instance lives, we
will also obtain database and queue connection information. Thus, when asked to
take action on instance $foo, we will:

1. Lookup the three-tuple of (database, queue, hostname) for that instance
2. Connect to that database and fetch the instance record
3. Connect to the queue and send the message to the proper hostname queue

The above differs from the current organization in two ways. First, we need to
do two database lookups before we know where the instance lives. Second, we
need to demand-connect to the appropriate database and queue. Both of these
have performance implications, but we believe we can mitigate the impacts
through the use of things like a memcache of instance mapping information and
pooling of connections to database and queue systems. The number of cells will
always be much smaller than the number of instances.

There are availability implications with this change since something like a
'nova list' which might query multiple cells could end up with a partial result
if there is a database failure in a cell.  A database failure within a cell
would cause larger issues than a partial list result so the expectation is that
it would be addressed quickly and cellsv2 will handle it by indicating in the
response that the data may not be complete.

Since this is very similar to what we have with current cells, in terms of
organization of resources, we have decided to call this "cellsv2" for
disambiguation.

After this work is complete there will no longer be a "no cells" deployment.
The default installation of Nova will be a single cell setup.

Benefits
--------

The benefits of this new organization are:

* Native sharding of the database and queue as a first-class-feature in nova.
  All of the code paths will go through the lookup procedure and thus we won't
  have the same feature parity issues as we do with current cells.

* No high-level replication of all the cell databases at the top. The API will
  need a database of its own for things like the instance index, but it will
  not need to replicate all the data at the top level.

* It draws a clear line between global and local data elements. Things like
  flavors and keypairs are clearly global concepts that need only live at the
  top level. Providing this separation allows compute nodes to become even more
  stateless and insulated from things like deleted/changed global data.

* Existing non-cells users will suddenly gain the ability to spawn a new "cell"
  from their existing deployment without changing their architecture. Simply
  adding information about the new database and queue systems to the new index
  will allow them to consume those resources.

* Existing cells users will need to fill out the cells mapping index, shutdown
  their existing cells synchronization service, and ultimately clean up their
  top level database. However, since the high-level organization is not
  substantially different, they will not have to re-architect their systems to
  move to cellsv2.

* Adding new sets of hosts as a new "cell" allows them to be plugged into a
  deployment and tested before allowing builds to be scheduled to them.

Comparison with current cells
-----------------------------

In reality, the proposed organization is nearly the same as what we currently
have in cells today. A cell mostly consists of a database, queue, and set of
compute nodes. The primary difference is that current cells require a
nova-cells service that synchronizes information up and down from the top level
to the child cell. Additionally, there are alternate code paths in
compute/api.py which handle routing messages to cells instead of directly down
to a compute host. Both of these differences are relevant to why we have a hard
time achieving feature and test parity with regular nova (because many things
take an alternate path with cells) and why it's hard to understand what is
going on (all the extra synchronization of data). The new proposed cellsv2
organization avoids both of these problems by letting things live where they
should, teaching nova to natively find the right db, queue, and compute node to
handle a given request.
