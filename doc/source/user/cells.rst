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

.. _cells:

=======
 Cells
=======

Before reading further, there is a nice overview presentation_ that
Andrew Laski gave at the Austin (Newton) summit which is worth watching.

.. _presentation: https://www.openstack.org/videos/video/nova-cells-v2-whats-going-on

Cells V1
========

Historically, Nova has depended on a single logical database and message queue
that all nodes depend on for communication and data persistence. This becomes
an issue for deployers as scaling and providing fault tolerance for these
systems is difficult.

We have an experimental feature in Nova called "cells", hereafter referred to
as "cells v1", which is used by some large deployments to partition compute
nodes into smaller groups, coupled with a database and queue. This seems to be
a well-liked and easy-to-understand arrangement of resources, but the
implementation of it has issues for maintenance and correctness.
See `Comparison with Cells V1`_ for more detail.

Status
~~~~~~

.. warning:: Cells v1 is deprecated in favor of Cells v2 as of the
             16.0.0 Pike release.

Cells v1 is considered experimental and receives much less testing than the
rest of Nova. For example, there is no job for testing cells v1 with Neutron.

The priority for the core team is implementation of and migration to cells v2.
Because of this, there are a few restrictions placed on cells v1:

#. Cells v1 is in feature freeze. This means no new feature proposals for cells
   v1 will be accepted by the core team, which includes but is not limited to
   API parity, e.g. supporting virtual interface attach/detach with Neutron.
#. Latent bugs caused by the cells v1 design will not be fixed, e.g.
   `bug 1489581 <https://bugs.launchpad.net/nova/+bug/1489581>`_. So if new
   tests are added to Tempest which trigger a latent bug in cells v1 it may not
   be fixed. However, regressions in working function should be tracked with
   bugs and fixed.

**Suffice it to say, new deployments of cells v1 are not encouraged.**

The restrictions above are basically meant to prioritize effort and focus on
getting cells v2 completed, and feature requests and hard to fix latent bugs
detract from that effort. Further discussion on this can be found in the
`2015/11/12 Nova meeting minutes
<http://eavesdrop.openstack.org/meetings/nova/2015/nova.2015-11-12-14.00.log.html>`_.

There are no plans to remove Cells V1 until V2 is usable by existing
deployments and there is a migration path.

.. _cells-v2:

Cells V2
========

* `Newton Summit Video - Nova Cells V2: What's Going On? <https://www.openstack.org/videos/austin-2016/nova-cells-v2-whats-going-on>`_
* `Pike Summit Video - Scaling Nova: How CellsV2 Affects Your Deployment <https://www.openstack.org/videos/boston-2017/scaling-nova-how-cellsv2-affects-your-deployment>`_
* `Queens Summit Video - Add Cellsv2 to your existing Nova deployment <https://www.openstack.org/videos/sydney-2017/adding-cellsv2-to-your-existing-nova-deployment>`_

Manifesto
~~~~~~~~~

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

Comparison with Cells V1
------------------------

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


Database split
~~~~~~~~~~~~~~

As mentioned above there is a split between global data and data that is local
to a cell.

The following is a breakdown of what data can uncontroversially considered
global versus local to a cell.  Missing data will be filled in as consensus is
reached on the data that is more difficult to cleanly place.  The missing data
is mostly concerned with scheduling and networking.

Global (API-level) Tables
-------------------------

instance_types
instance_type_projects
instance_type_extra_specs
quotas
project_user_quotas
quota_classes
quota_usages
security_groups
security_group_rules
security_group_default_rules
provider_fw_rules
key_pairs
migrations
networks
tags

Cell-level Tables
-----------------

instances
instance_info_caches
instance_extra
instance_metadata
instance_system_metadata
instance_faults
instance_actions
instance_actions_events
instance_id_mappings
pci_devices
block_device_mapping
virtual_interfaces

Setup of Cells V2
=================

Overview
~~~~~~~~

As more of the CellsV2 implementation is finished, all operators are
required to make changes to their deployment. For all deployments
(even those that only intend to have one cell), these changes are
configuration-related, both in the main nova configuration file as
well as some extra records in the databases.

All nova deployments must now have the following databases available
and configured:

1. The "API" database
2. One special "cell" database called "cell0"
3. One (or eventually more) "cell" databases

Thus, a small nova deployment will have an API database, a cell0, and
what we will call here a "cell1" database. High-level tracking
information is kept in the API database. Instances that are never
scheduled are relegated to the cell0 database, which is effectively a
graveyard of instances that failed to start. All successful/running
instances are stored in "cell1".

First Time Setup
~~~~~~~~~~~~~~~~

Since there is only one API database, the connection information for
it is stored in the nova.conf file.
::

  [api_database]
  connection = mysql+pymysql://root:secretmysql@dbserver/nova_api?charset=utf8

Since there may be multiple "cell" databases (and in fact everyone
will have cell0 and cell1 at a minimum), connection info for these is
stored in the API database. Thus, you must have connection information
in your config file for the API database before continuing to the
steps below, so that `nova-manage` can find your other databases.

The following examples show the full expanded command line usage of
the setup commands. This is to make it easier to visualize which of
the various URLs are used by each of the commands. However, you should
be able to put all of that in the config file and `nova-manage` will
use those values. If need be, you can create separate config files and
pass them as `nova-manage --config-file foo.conf` to control the
behavior without specifying things on the command lines.

The commands below use the API database so remember to run
`nova-manage api_db sync` first.

First we will create the necessary records for the cell0 database. To
do that we use `nova-manage` like this::

  nova-manage cell_v2 map_cell0 --database_connection \
    mysql+pymysql://root:secretmysql@dbserver/nova_cell0?charset=utf8

.. note:: If you don't specify `--database_connection` then
          `nova-manage` will use the `[database]/connection` value
          from your config file, and mangle the database name to have
          a `_cell0` suffix.
.. warning:: If your databases are on separate hosts then you should specify
             `--database_connection` or make certain that the nova.conf
             being used has the `[database]/connection` value pointing to the
             same user/password/host that will work for the cell0 database.
             If the cell0 mapping was created incorrectly, it can be deleted
             using the `nova-manage cell_v2 delete_cell` command and then run
             `map_cell0` again with the proper database connection value.

Since no hosts are ever in cell0, nothing further is required for its
setup. Note that all deployments only ever have one cell0, as it is
special, so once you have done this step you never need to do it
again, even if you add more regular cells.

Now, we must create another cell which will be our first "regular"
cell, which has actual compute hosts in it, and to which instances can
actually be scheduled. First, we create the cell record like this::

  nova-manage cell_v2 create_cell --verbose --name cell1 \
    --database_connection  mysql+pymysql://root:secretmysql@127.0.0.1/nova?charset=utf8
    --transport-url rabbit://stackrabbit:secretrabbit@mqserver:5672/

.. note:: If you don't specify the database and transport urls then
          `nova-manage` will use the
          `[database]/connection` and `[DEFAULT]/transport_url` values
          from the config file.

.. note:: At this point, the API database can now find the cell
          database, and further commands will attempt to look
          inside. If this is a completely fresh database (such as if
          you're adding a cell, or if this is a new deployment), then
          you will need to run `nova-manage db sync` on it to
          initialize the schema.

The `nova-manage cell_v2 create_cell` command will print the UUID of the
newly-created cell if `--verbose` is passed, which is useful if you
need to run commands like `discover_hosts` targeted at a specific
cell.

Now we have a cell, but no hosts are in it which means the scheduler
will never actually place instances there. The next step is to scan
the database for compute node records and add them into the cell we
just created. For this step, you must have had a compute node started
such that it registers itself as a running service. Once that has
happened, you can scan and add it to the cell::

  nova-manage cell_v2 discover_hosts

This command will connect to any databases for which you have created
cells (as above), look for hosts that have registered themselves
there, and map those hosts in the API database so that
they are visible to the scheduler as available targets for
instances. Any time you add more compute hosts to a cell, you need to
re-run this command to map them from the top-level so they can be
utilized.

References
~~~~~~~~~~

* :doc:`nova-manage man page </cli/nova-manage>`

Step-By-Step for Common Use Cases
=================================

The following are step-by-step examples for common use cases setting
up Cells V2. This is intended as a quick reference that puts together
everything explained in `Setup of Cells V2`_. It is assumed that you have
followed all other install steps for Nova and are setting up Cells V2
specifically at this point.

Fresh Install
~~~~~~~~~~~~~

You are installing Nova for the first time and have no compute hosts in the
database yet. This will set up a single cell Nova deployment.

1. Reminder: You should have already created and synced the Nova API database
   by creating a database, configuring its connection in the
   ``[api_database]/connection`` setting in the Nova configuration file, and
   running ``nova-manage api_db sync``.

2. Create a database for cell0. If you are going to pass the database
   connection url on the command line in step 3, you can name the cell0
   database whatever you want. If you are not going to pass the database url on
   the command line in step 3, you need to name the cell0 database based on the
   name of your existing Nova database: <Nova database name>_cell0. For
   example, if your Nova database is named ``nova``, then your cell0 database
   should be named ``nova_cell0``.

3. Run the ``map_cell0`` command to create and map cell0::

     nova-manage cell_v2 map_cell0 \
       --database_connection <database connection url>

   The database connection url is generated based on the
   ``[database]/connection`` setting in the Nova configuration file if not
   specified on the command line.

4. Run ``nova-manage db sync`` to populate the cell0 database with a schema.
   The ``db sync`` command reads the database connection for cell0 that was
   created in step 3.

5. Run the ``create_cell`` command to create the single cell which will contain
   your compute hosts::

     nova-manage cell_v2 create_cell --name <name> \
       --transport-url <transport url for message queue> \
       --database_connection <database connection url>

   The transport url is taken from the ``[DEFAULT]/transport_url`` setting in
   the Nova configuration file if not specified on the command line. The
   database url is taken from the ``[database]/connection`` setting in the Nova
   configuration file if not specified on the command line.

6. Configure your compute host(s), making sure ``[DEFAULT]/transport_url``
   matches the transport URL for the cell created in step 5, and start the
   nova-compute service. Before step 7, make sure you have compute hosts in the
   database by running::
  
     nova service-list --binary nova-compute

7. Run the ``discover_hosts`` command to map compute hosts to the single cell
   by running::

     nova-manage cell_v2 discover_hosts

   The command will search for compute hosts in the database of the cell you
   created in step 5 and map them to the cell. You can also configure a
   periodic task to have Nova discover new hosts automatically by setting
   the ``[scheduler]/discover_hosts_in_cells_interval`` to a time interval in
   seconds. The periodic task is run by the nova-scheduler service, so you must
   be sure to configure it on all of your nova-scheduler hosts.

.. note:: Remember: In the future, whenever you add new compute hosts, you
          will need to run the ``discover_hosts`` command after starting them
          to map them to the cell if you did not configure the automatic host
          discovery in step 7.

Upgrade (minimal)
~~~~~~~~~~~~~~~~~

You are upgrading an existing Nova install and have compute hosts in the
database. This will set up a single cell Nova deployment.

1. If you haven't already created a cell0 database in a prior release,
   create a database for cell0 with a name based on the name of your Nova
   database: <Nova database name>_cell0. If your Nova database is named
   ``nova``, then your cell0 database should be named ``nova_cell0``.

.. warning:: In Newton, the ``simple_cell_setup`` command expects the name of
             the cell0 database to be based on the name of the Nova API
             database: <Nova API database name>_cell0 and the database
             connection url is taken from the ``[api_database]/connection``
             setting in the Nova configuration file.

2. Run the ``simple_cell_setup`` command to create and map cell0, create and
   map the single cell, and map existing compute hosts and instances to the
   single cell::

     nova-manage cell_v2 simple_cell_setup \
       --transport-url <transport url for message queue>

   The transport url is taken from the ``[DEFAULT]/transport_url`` setting in
   the Nova configuration file if not specified on the command line. The
   database connection url will be generated based on the
   ``[database]/connection`` setting in the Nova configuration file.

.. note:: Remember: In the future, whenever you add new compute hosts, you
          will need to run the ``discover_hosts`` command after starting them
          to map them to the cell. You can also configure a periodic task to
          have Nova discover new hosts automatically by setting the
          ``[scheduler]/discover_hosts_in_cells_interval`` to a time interval
          in seconds. The periodic task is run by the nova-scheduler service,
          so you must be sure to configure it on all of your nova-scheduler
          hosts.

Upgrade with Cells V1
~~~~~~~~~~~~~~~~~~~~~

You are upgrading an existing Nova install that has Cells V1 enabled and have
compute hosts in your databases. This will set up a multiple cell Nova
deployment. At this time, it is recommended to keep Cells V1 enabled during and
after the upgrade as multiple Cells V2 cell support is not fully finished and
may not work properly in all scenarios. These upgrade steps will help ensure a
simple cutover from Cells V1 to Cells V2 in the future.

1. If you haven't already created a cell0 database in a prior release,
   create a database for cell0. If you are going to pass the database
   connection url on the command line in step 2, you can name the cell0
   database whatever you want. If you are not going to pass the database url on
   the command line in step 2, you need to name the cell0 database based on the
   name of your existing Nova database: <Nova database name>_cell0. For
   example, if your Nova database is named ``nova``, then your cell0 database
   should be named ``nova_cell0``.

2. Run the ``map_cell0`` command to create and map cell0::

     nova-manage cell_v2 map_cell0 \
       --database_connection <database connection url>

   The database connection url is generated based on the
   ``[database]/connection`` setting in the Nova configuration file if not
   specified on the command line.

3. Run ``nova-manage db sync`` to populate the cell0 database with a schema.
   The ``db sync`` command reads the database connection for cell0 that was
   created in step 2.

4. Run the ``create_cell`` command to create cells which will contain your
   compute hosts::

     nova-manage cell_v2 create_cell --name <cell name> \
       --transport-url <transport url for message queue> \
       --database_connection <database connection url>

   You will need to repeat this step for each cell in your deployment. Your
   existing cell database will be re-used -- this simply informs the top-level
   API database about your existing cell databases.

   It is a good idea to specify a name for the new cell you create so you can
   easily look up cell uuids with the ``list_cells`` command later if needed.

   The transport url is taken from the ``[DEFAULT]/transport_url`` setting in
   the Nova configuration file if not specified on the command line. The
   database url is taken from the ``[database]/connection`` setting in the Nova
   configuration file if not specified on the command line. If you are not
   going to specify ``--database_connection`` and ``--transport-url`` on the
   command line, be sure to specify your existing cell Nova configuration
   file::

     nova-manage --config-file <cell nova.conf> cell_v2 create_cell \
       --name <cell name>

5. Run the ``discover_hosts`` command to map compute hosts to cells::

     nova-manage cell_v2 discover_hosts --cell_uuid <cell uuid>

   You will need to repeat this step for each cell in your deployment unless
   you omit the ``--cell_uuid`` option. If the cell uuid is not specified on
   the command line, ``discover_hosts`` will search for compute hosts in each
   cell database and map them to the corresponding cell. You can use the
   ``list_cells`` command to look up cell uuids if you are going to specify
   ``--cell_uuid``.

   You can also configure a periodic task to have Nova discover new hosts
   automatically by setting the
   ``[scheduler]/discover_hosts_in_cells_interval`` to a time interval in
   seconds. The periodic task is run by the nova-scheduler service, so you must
   be sure to configure it on all of your nova-scheduler hosts.

6. Run the ``map_instances`` command to map instances to cells::

     nova-manage cell_v2 map_instances --cell_uuid <cell uuid> \
       --max-count <max count>

   You will need to repeat this step for each cell in your deployment. You can
   use the ``list_cells`` command to look up cell uuids.

   The ``--max-count`` option can be specified if you would like to limit the
   number of instances to map in a single run. If ``--max-count`` is not
   specified, all instances will be mapped. Repeated runs of the command will
   start from where the last run finished so it is not necessary to increase
   ``--max-count`` to finish. An exit code of 0 indicates that all instances
   have been mapped. An exit code of 1 indicates that there are remaining
   instances that need to be mapped.

.. note:: Remember: In the future, whenever you add new compute hosts, you
          will need to run the ``discover_hosts`` command after starting them
          to map them to a cell if you did not configure the automatic host
          discovery in step 5.

Adding a new cell to an existing deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To expand your deployment with a new cell, first follow the usual steps for
standing up a new Cells V1 cell. After that is finished, follow step 4 in
`Upgrade with Cells V1`_ to create a new Cells V2 cell for it. If you have
added new compute hosts for the new cell, you will also need to run the
``discover_hosts`` command after starting them to map them to the new cell if
you did not configure the automatic host discovery as described in step 5 in
`Upgrade with Cells V1`_.

References
~~~~~~~~~~

* :doc:`nova-manage man page </cli/nova-manage>`

FAQs
====

#. How do I find out which hosts are bound to which cell?

   There are a couple of ways to do this.

   1. Run ``nova-manage --config-file <cell config> host list``. This will
      only lists hosts in the provided cell nova.conf. Note, however, that
      this command is deprecated as of the 16.0.0 Pike release.

   2. Run ``nova-manage cell_v2 discover_hosts --verbose``. This does not
      produce a report but if you are trying to determine if a host is in a
      cell you can run this and it will report any hosts that are not yet
      mapped to a cell and map them. This command is idempotent.

   3. Run ``nova-manage cell_v2 list_hosts``. This will list hosts in all
      cells. If you want to list hosts in a specific cell, you can run
      ``nova-manage cell_v2 list_hosts --cell_uuid <cell_uuid>``.

#. I updated the database_connection and/or transport_url in a cell using the
   ``nova-manage cell_v2 update_cell`` command but the API is still trying to
   use the old settings.

   The cell mappings are cached in the nova-api service worker so you will need
   to restart the worker process to rebuild the cache. Note that there is
   another global cache tied to request contexts, which is used in the
   nova-conductor and nova-scheduler services, so you might need to do the same
   if you are having the same issue in those services. As of the 16.0.0 Pike
   release there is no timer on the cache or hook to refresh the cache using a
   SIGHUP to the service.

#. I have upgraded from Newton to Ocata and I can list instances but I get a
   404 NotFound error when I try to get details on a specific instance.

   Instances need to be mapped to cells so the API knows which cell an instance
   lives in. When upgrading, the ``nova-manage cell_v2 simple_cell_setup``
   command will automatically map the instances to the single cell which is
   backed by the existing nova database. If you have already upgraded
   and did not use the ``simple_cell_setup`` command, you can run the
   ``nova-manage cell_v2 map_instances --cell_uuid <cell_uuid>`` command to
   map all instances in the given cell. See the :ref:`man-page-cells-v2` man
   page for details on command usage.

#. Should I change any of the ``[cells]`` configuration options for Cells v2?

   **NO**. Those options are for Cells v1 usage only and are not used at all
   for Cells v2. That includes the ``nova-cells`` service - it has nothing
   to do with Cells v2.
