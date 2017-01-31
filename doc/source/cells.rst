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


Cells V2
========

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

* `man pages for the cells v2 commands <http://docs.openstack.org/developer/nova/man/nova-manage.html#nova-cells-v2>`_
