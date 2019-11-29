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
Nova. Nova has had this since the early days.

Secondly, we want no downtime during upgrades of the Nova control plane.
This document is trying to describe how we can achieve that.

Once we have introduced the key concepts relating to upgrade, we will
introduce the process needed for a no downtime upgrade of nova.

.. _minimal_downtime_upgrade:

Minimal Downtime Upgrade Process
--------------------------------


Plan your upgrade
'''''''''''''''''

* Read and ensure you understand the release notes for the next release.

* You should ensure all required steps from the previous upgrade have been
  completed, such as data migrations.

* Make a backup of your database. Nova does not support downgrading of the
  database. Hence, in case of upgrade failure, restoring database from backup
  is the only choice.

* During upgrade be aware that there will be additional load on nova-conductor.
  You may find you need to add extra nova-conductor workers to deal with the
  additional upgrade related load.


Rolling upgrade process
'''''''''''''''''''''''

To reduce downtime, the compute services can be upgraded in a rolling fashion. It
means upgrading a few services at a time. This results in a condition where
both old (N) and new (N+1) nova-compute services co-exist for a certain time
period. Note that, there is no upgrade of the hypervisor here, this is just
upgrading the nova services. If reduced downtime is not a concern (or lower
complexity is desired), all services may be taken down and restarted at the
same time.

#. Before maintenance window:

   * Start the process with the controller node. Install the code for the next
     version of Nova, either in a venv or a separate control plane node,
     including all the python dependencies.

   * Using the newly installed nova code, run the DB sync. First run
     ``nova-manage api_db sync``, then ``nova-manage db sync``. ``nova-manage
     db sync`` should be run for all cell databases, including ``cell0``. If
     necessary, the ``--config-file`` argument can be used to point to the
     correct ``nova.conf`` file for the given cell.

     These schema change operations should have minimal or no effect on
     performance, and should not cause any operations to fail.

   * At this point, new columns and tables may exist in the database. These
     DB schema changes are done in a way that both the N and N+1 release can
     perform operations against the same schema.

#. During maintenance window:

   * Several nova services rely on the external placement service being at the
     latest level. Therefore, you must upgrade placement before any nova
     services. See the
     :placement-doc:`placement upgrade notes <admin/upgrade-notes.html>` for
     more details on upgrading the placement service.

   * For maximum safety (no failed API operations), gracefully shutdown all
     the services (i.e. SIG_TERM) except nova-compute.

   * Before restarting services with new code, perform the release-specific
     readiness check with ``nova-status upgrade check``. See the
     :ref:`nova-status upgrade check <nova-status-checks>` for more details
     on status check.

   * Start all services on the new code, with
     ``[upgrade_levels]compute=auto`` in nova.conf.  It is safest to
     start nova-conductor first and nova-api last. Note that you may
     use a static alias name instead of ``auto``, such as
     ``[upgrade_levels]compute=<release_name>``. Also note that this step is
     only required if compute services are not upgraded in lock-step
     with the control services.

   * If desired, gracefully shutdown nova-compute (i.e. SIG_TERM)
     services in small batches, then start the new version of the code
     with: ``[upgrade_levels]compute=auto``. If this batch-based approach
     is used, only a few compute nodes will have any delayed API
     actions, and to ensure there is enough capacity online to service
     any boot requests that happen during this time.

#. After maintenance window:

   * Once all services are running the new code, double check in the DB that
     there are no old orphaned service records using `nova service-list`.

   * Now that all services are upgraded, we need to send the SIG_HUP signal, so all
     the services clear any cached service version data. When a new service
     starts, it automatically detects which version of the compute RPC protocol
     to use, and it can decide if it is safe to do any online data migrations.
     Note, if you used a static value for the upgrade_level, such as
     ``[upgrade_levels]compute=<release_name>``, you must update nova.conf to remove
     that configuration value and do a full service restart.

   * Now all the services are upgraded and signaled, the system is able to use
     the latest version of the RPC protocol and can access all of the
     features in the new release.

   * Once all the services are running the latest version of the code, and all
     the services are aware they all have been upgraded, it is safe to
     transform the data in the database into its new format. While some of this
     work happens on demand when the system reads a database row that needs
     updating, we must get all the data transformed into the current version
     before the next upgrade. Additionally, some data may not be transformed
     automatically so performing the data migration is necessary to avoid
     performance degradation due to compatibility routines.

   * This process can put significant extra write load on the
     database.  Complete all online data migrations using:
     ``nova-manage db online_data_migrations --max-count <number>``. Note
     that you can use the ``--max-count`` argument to reduce the load this
     operation will place on the database, which allows you to run a
     small chunk of the migrations until all of the work is done. The chunk size
     you should use depends on your infrastructure and how much additional load
     you can impose on the database. To reduce load, perform smaller batches
     with delays between chunks. To reduce time to completion, run larger batches.
     Each time it is run, the command will show a summary of completed and remaining
     records. If using the ``--max-count`` option, the command should be rerun
     while it returns exit status 1 (which indicates that some migrations took
     effect, and more work may remain to be done), even if some migrations
     produce errors. If all possible migrations have completed and some are
     still producing errors, exit status 2 will be returned. In this case, the
     cause of the errors should be investigated and resolved. Migrations should be
     considered successfully completed only when the command returns exit status 0.

   * At this point, you must also ensure you update the configuration, to stop
     using any deprecated features or options, and perform any required work
     to transition to alternative features. All the deprecated options should
     be supported for one cycle, but should be removed before your next
     upgrade is performed.


Current Database Upgrade Types
------------------------------

Currently Nova has 2 types of database upgrades that are in use.

#. Schema Migrations
#. Data Migrations


Schema Migrations
''''''''''''''''''

Schema migrations are defined in
``nova/db/sqlalchemy/migrate_repo/versions`` and in
``nova/db/sqlalchemy/api_migrations/migrate_repo/versions``. They are
the routines that transform our database structure, which should be
additive and able to be applied to a running system before service
code has been upgraded.

.. note::

  The API database migrations should be assumed to run before the
  migrations for the main/cell databases. This is because the former
  contains information about how to find and connect to the latter.
  Some management commands that operate on multiple cells will attempt
  to list and iterate over cell mapping records, which require a
  functioning API database schema.

.. _data-migrations:

Data Migrations
'''''''''''''''''

Online data migrations occur in two places:

#. Inline migrations that occur as part of normal run-time
   activity as data is read in the old format and written in the
   new format
#. Background online migrations that are performed using
   ``nova-manage`` to complete transformations that will not occur
   incidentally due to normal runtime activity.

An example of online data migrations are the flavor migrations done as part
of Nova object version 1.18. This included a transient migration of flavor
storage from one database location to another.

.. note::

  Database downgrades are not supported.

Migration policy:
'''''''''''''''''

The following guidelines for schema and data migrations are followed in order
to ease upgrades:

* Additive schema migrations - In general, almost all schema migrations should
  be additive.  Put simply, they should only create elements like columns,
  indices, and tables.

* Subtractive schema migrations - To remove an element like a column or table
  during the N release cycle:

  #. The element must be deprecated and retained for backward compatibility.
     (This allows for graceful upgrade from N to N+1.)

  #. Data migration, by the objects layer, must completely migrate data from
     the old version of the schema to the new version.

     * `Data migration example
       <http://specs.openstack.org/openstack/nova-specs/specs/kilo/implemented/flavor-from-sysmeta-to-blob.html>`_
     * `Data migration enforcement example
       <https://review.opendev.org/#/c/174480/15/nova/db/sqlalchemy/migrate_repo/versions/291_enforce_flavors_migrated.py>`_
       (for sqlalchemy migrate/deprecated scripts):

  #. The column can then be removed with a migration at the start of N+2.

* All schema migrations should be idempotent.  (For example, a migration
  should check if an element exists in the schema before attempting to add
  it.)  This logic comes for free in the autogenerated workflow of
  the online migrations.

* Constraints - When adding a foreign or unique key constraint, the schema
  migration code needs to handle possible problems with data before applying
  the constraint. (Example:  A unique constraint must clean up duplicate
  records before applying said constraint.)

* Data migrations - As mentioned above, data migrations will be done in an
  online fashion by custom code in the object layer that handles moving data
  between the old and new portions of the schema.  In addition, for each type
  of data migration performed, there should exist a nova-manage option for an
  operator to manually request that rows be migrated.

  * See `flavor migration spec
    <http://specs.openstack.org/openstack/nova-specs/specs/kilo/implemented/flavor-from-sysmeta-to-blob.html>`_
    for an example of data migrations in the object layer.

*Future* work -
   #. Adding plumbing to enforce that relevant data migrations are completed
      before running `contract` in the expand/migrate/contract schema migration
      workflow.  A potential solution would be for `contract` to run a gating
      test for each specific subtract operation to determine if the operation
      can be completed.

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

    .. note::

      The procedure for rolling upgrades with multiple cells v2 cells is not
      yet determined.

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

    .. note::

      While this is true for the RabbitMQ RPC backend, we need to confirm
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
    you can drop bits of the scheme that are no long needed,
    i.e. contract. This happens multiple cycles after we have stopped
    using a particular piece of schema, and can happen in a schema
    migration without affecting runtime code.

Online Data Migrations using objects
    In Kilo we are moving all data migration into the DB objects code.
    When trying to migrate data in the database from the old format to the
    new format, this is done in the object code when reading or saving things
    that are in the old format. For records that are not updated, you need to
    run a background process to convert those records into the newer format.
    This process must be completed before you contract the database schema.

DB prune deleted rows
    Currently resources are soft deleted in the main database, so users are able
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


Testing
-------

Once we have all the pieces in place, we hope to move the Grenade testing
to follow this new pattern.

The current tests only cover the existing upgrade process where:

* old computes can run with new control plane
* but control plane is turned off for DB migrations
