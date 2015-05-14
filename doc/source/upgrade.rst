..
      Copyright 2014 Rackspace
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

Upgrades
========

Nova aims to provide upgrades with minimal downtime.

Firstly, the data plane. There should be no VM downtime when you upgrade
Nova. Nova has had this since the early days, with the exception of
some nova-network related services.

Secondly, we want no downtime during upgrades of the Nova control plane.
This document is trying to describe how we can achieve that.

Once we have introduced the key concepts relating to upgrade, we will
introduce the process needed for a no downtime upgrade of nova.

Concepts
--------

Here are the key concepts you need to know before reading the section on the
upgrade process:

RPC version pinning
    Through careful RPC versioning, newer nodes are able to talk to older
    nova-compute nodes. When upgrading control plane nodes, we can pin them
    at an older version of the compute RPC API, until all the compute nodes
    are able to be upgraded.
    https://wiki.openstack.org/wiki/RpcMajorVersionUpdates

Online Configuration Reload
    During the upgrade, we pin new serves at the older RPC version. When all
    services are updated to use newer code, we need to unpin them so we are
    able to use any new functionality.
    To avoid having to restart the service, using the current SIGHUP signal
    handling, or otherwise, ideally we need a way to update the currently
    running process to use the latest configuration.

Graceful service shutdown
    Many nova services are python processes listening for messages on a
    AMQP queue, including nova-compute. When sending the process the SIGTERM
    the process stops getting new work from its queue, completes any
    outstanding work, then terminates. During this process, messages can be
    left on the queue for when the python process starts back up.
    This gives us a way to shutdown a service using older code, and start
    up a service using newer code with minimal impact. If its a service that
    can have multiple workers, like nova-conductor, you can usually add the
    new workers before the graceful shutdown of the old workers. In the case
    of singleton services, like nova-compute, some actions could be delayed
    during the restart, but ideally no actions should fail due to the restart.
    NOTE: while this is true for the RabbitMQ RPC backend, we need to confirm
    what happens for other RPC backends.

API load balancer draining
    When upgrading API nodes, you can make your load balancer only send new
    connections to the newer API nodes, allowing for a seamless update of your
    API nodes.

Expand/Contract DB Migrations
    Modern databases are able to make many schema changes while you are still
    writing to the database. Taking this a step further, we can make all DB
    changes by first adding the new structures, expanding. Then you can slowly
    move all the data into a new location and format. Once that is complete,
    you can drop bits of the scheme that are no long needed, i.e. contract.
    We have plans to implement this here:
    https://review.openstack.org/#/c/102545/5/specs/juno/online-schema-changes.rst,cm

Online Data Migrations using objects
    In Kilo we are moving all data migration into the DB objects code.
    When trying to migrate data in the database from the old format to the
    new format, this is done in the object code when reading or saving things
    that are in the old format. For records that are not updated, you need to
    run a background process to convert those records into the newer format.
    This process must be completed before you contract the database schema.
    We have the first example of this happening here:
    http://specs.openstack.org/openstack/nova-specs/specs/kilo/approved/flavor-from-sysmeta-to-blob.html

DB prune deleted rows
    Currently resources are soft deleted in the database, so users are able
    to track instances in the DB that are created and destroyed in production.
    However, most people have a data retention policy, of say 30 days or 90
    days after which they will want to delete those entries. Not deleting
    those entries affects DB performance as indices grow very large and data
    migrations take longer as there is more data to migrate.

nova-conductor object backports
    RPC pinning ensures new services can talk to the older service's method
    signatures. But many of the parameters are objects that may well be too
    new for the old service to understand, so you are able to send the object
    back to the nova-conductor to be downgraded to a version the older service
    can understand.


Process
-------

NOTE:
    This still requires much work before it can become reality.
    This is more an aspirational plan that helps describe how all the
    pieces of the jigsaw fit together.

This is the planned process for a zero downtime upgrade:

#. Prune deleted DB rows, check previous migrations are complete

#. Expand DB schema (e.g. add new column)

#. Pin RPC versions for all services that are upgraded from this point,
   using the current version

#. Upgrade all nova-conductor nodes (to do object backports)

#. Upgrade all other services, except nova-compute and nova-api,
   using graceful shutdown

#. Upgrade nova-compute nodes (this is the bulk of the work).

#. Unpin RPC versions

#. Add new API nodes, and enable new features, while using a load balancer
   to "drain" the traffic from old API nodes

#. Run the new nova-manage command that ensures all DB records are "upgraded"
   to new data version

#. "Contract" DB schema (e.g. drop unused columns)


Testing
-------

Once we have all the pieces in place, we hope to move the Grenade testing
to follow this new pattern.

The current tests only cover the existing upgrade process where:
* old computes can run with new control plane
* but control plane is turned off for DB migrations

Unresolved issues
-----------------

Ideally you could rollback. We would need to add some kind of object data
version pinning, so you can be running all new code to some extent, before
there is no path back. Or have some way of reversing the data migration
before the final contract.

It is unknown how expensive on demand object backports would be. We could
instead always send older versions of objects until the RPC pin is removed,
but that means we might have new code getting old objects, which is currently
not the case.
