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

===================
 Cells Layout (v2)
===================

This document describes the layout of a deployment with Cells
version 2, including deployment considerations for security and
scale. It is focused on code present in Pike and later, and while it
is geared towards people who want to have multiple cells for whatever
reason, the nature of the cellsv2 support in Nova means that it
applies in some way to all deployments.

.. note:: The concepts laid out in this document do not in any way
          relate to CellsV1, which includes the ``nova-cells``
          service, and the ``[cells]`` section of the configuration
          file. For more information on the differences, see the main
          :ref:`cells` page.

Concepts
========

A basic Nova system consists of the following components:

* The nova-api service which provides the external REST API to users.
* The nova-scheduler and placement services which are responsible
  for tracking resources and deciding which compute node instances
  should be on.
* An "API database" that is used primarily by nova-api and
  nova-scheduler (called *API-level services* below) to track location
  information about instances, as well as a temporary location for
  instances being built but not yet scheduled.
* The nova-conductor service which offloads long-running tasks for the
  API-level service, as well as insulates compute nodes from direct
  database access
* The nova-compute service which manages the virt driver and
  hypervisor host.
* A "cell database" which is used by API, conductor and compute
  services, and which houses the majority of the information about
  instances.
* A "cell0 database" which is just like the cell database, but
  contains only instances that failed to be scheduled.
* A message queue which allows the services to communicate with each
  other via RPC.

All deployments have at least the above components. Small deployments
likely have a single message queue that all services share, and a
single database server which hosts the API database, a single cell
database, as well as the required cell0 database. This is considered a
"single-cell deployment" because it only has one "real" cell. The
cell0 database mimics a regular cell, but has no compute nodes and is
used only as a place to put instances that fail to land on a real
compute node (and thus a real cell).

The purpose of the cells functionality in nova is specifically to
allow larger deployments to shard their many compute nodes into cells,
each of which has a database and message queue. The API database is
always and only global, but there can be many cell databases (where
the bulk of the instance information lives), each with a portion of
the instances for the entire deployment within.

All of the nova services use a configuration file, all of which will
at a minimum specify a message queue endpoint
(i.e. ``[DEFAULT]/transport_url``). Most of the services also require
configuration of database connection information
(i.e. ``[database]/connection``). API-level services that need access
to the global routing and placement information will also be
configured to reach the API database
(i.e. ``[api_database]/connection``).

.. note:: The pair of ``transport_url`` and ``[database]/connection``
          configured for a service defines what cell a service lives
          in.

API-level services need to be able to contact other services in all of
the cells. Since they only have one configured ``transport_url`` and
``[database]/connection`` they look up the information for the other
cells in the API database, with records called *cell mappings*.

.. note:: The API database must have cell mapping records that match
          the ``transport_url`` and ``[database]/connection``
          configuration elements of the lower-level services. See the
          ``nova-manage`` :ref:`man-page-cells-v2` commands for more
          information about how to create and examine these records.

Service Layout
==============

The services generally have a well-defined communication pattern that
dictates their layout in a deployment. In a small/simple scenario, the
rules do not have much of an impact as all the services can
communicate with each other on a single message bus and in a single
cell database. However, as the deployment grows, scaling and security
concerns may drive separation and isolation of the services.

Simple
------

This is a diagram of the basic services that a simple (single-cell)
deployment would have, as well as the relationships
(i.e. communication paths) between them:

.. graphviz::

  digraph services {
    graph [pad="0.35", ranksep="0.65", nodesep="0.55", concentrate=true];
    node [fontsize=10 fontname="Monospace"];
    edge [arrowhead="normal", arrowsize="0.8"];
    labelloc=bottom;
    labeljust=left;

    { rank=same
      api [label="nova-api"]
      apidb [label="API Database" shape="box"]
      scheduler [label="nova-scheduler"]
    }
    { rank=same
      mq [label="MQ" shape="diamond"]
      conductor [label="nova-conductor"]
    }
    { rank=same
      cell0db [label="Cell0 Database" shape="box"]
      celldb [label="Cell Database" shape="box"]
      compute [label="nova-compute"]
    }

    api -> mq -> compute
    conductor -> mq -> scheduler

    api -> apidb
    api -> cell0db
    api -> celldb

    conductor -> apidb
    conductor -> cell0db
    conductor -> celldb
  }

All of the services are configured to talk to each other over the same
message bus, and there is only one cell database where live instance
data resides. The cell0 database is present (and required) but as no
compute nodes are connected to it, this is still a "single cell"
deployment.

Multiple Cells
--------------

In order to shard the services into multiple cells, a number of things
must happen. First, the message bus must be split into pieces along
the same lines as the cell database. Second, a dedicated conductor
must be run for the API-level services, with access to the API
database and a dedicated message queue. We call this *super conductor*
to distinguish its place and purpose from the per-cell conductor nodes.

.. graphviz::

  digraph services2 {
    graph [pad="0.35", ranksep="0.65", nodesep="0.55", concentrate=true];
    node [fontsize=10 fontname="Monospace"];
    edge [arrowhead="normal", arrowsize="0.8"];
    labelloc=bottom;
    labeljust=left;

    subgraph api {
      api [label="nova-api"]
      scheduler [label="nova-scheduler"]
      conductor [label="super conductor"]
      { rank=same
        apimq [label="API MQ" shape="diamond"]
        apidb [label="API Database" shape="box"]
      }

      api -> apimq -> conductor
      api -> apidb
      conductor -> apimq -> scheduler
      conductor -> apidb
    }

    subgraph clustercell0 {
      label="Cell 0"
      color=green
      cell0db [label="Cell Database" shape="box"]
    }

    subgraph clustercell1 {
      label="Cell 1"
      color=blue
      mq1 [label="Cell MQ" shape="diamond"]
      cell1db [label="Cell Database" shape="box"]
      conductor1 [label="nova-conductor"]
      compute1 [label="nova-compute"]

      conductor1 -> mq1 -> compute1
      conductor1 -> cell1db

    }

    subgraph clustercell2 {
      label="Cell 2"
      color=red
      mq2 [label="Cell MQ" shape="diamond"]
      cell2db [label="Cell Database" shape="box"]
      conductor2 [label="nova-conductor"]
      compute2 [label="nova-compute"]

      conductor2 -> mq2 -> compute2
      conductor2 -> cell2db
    }

    api -> mq1 -> conductor1
    api -> mq2 -> conductor2
    api -> cell0db
    api -> cell1db
    api -> cell2db

    conductor -> cell0db
    conductor -> cell1db
    conductor -> mq1
    conductor -> cell2db
    conductor -> mq2
  }

It is important to note that services in the lower cell boxes only
have the ability to call back to the placement API but cannot access
any other API-layer services via RPC, nor do they have access to the
API database for global visibility of resources across the cloud.
This is intentional and provides security and failure domain
isolation benefits, but also has impacts on some things that would
otherwise require this any-to-any communication style. Check the
release notes for the version of Nova you are using for the most
up-to-date information about any caveats that may be present due to
this limitation.

Caveats of a Multi-Cell deployment
----------------------------------

.. note:: This information is correct as of the Pike release. Where
          improvements have been made or issues fixed, they are noted per
          item.

Cross-cell instance migrations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently it is not possible to migrate an instance from a host in one
cell to a host in another cell. This may be possible in the future,
but it is currently unsupported. This impacts cold migration,
resizes, live migrations, evacuate, and unshelve operations.

Quota-related quirks
~~~~~~~~~~~~~~~~~~~~

Quotas are now calculated live at the point at which an operation
would consume more resource, instead of being kept statically in the
database. This means that a multi-cell environment may incorrectly
calculate the usage of a tenant if one of the cells is unreachable, as
those resources cannot be counted. In this case, the tenant may be
able to consume more resource from one of the available cells, putting
them far over quota when the unreachable cell returns. In the future,
placement will provide us with a consistent way to calculate usage
independent of the actual cell being reachable.

Performance of listing instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note:: This has been resolved in the Queens release [#]_.

With multiple cells, the instance list operation may not sort and
paginate results properly when crossing multiple cell
boundaries. Further, the performance of a sorted list operation will
be considerably slower than with a single cell.

Notifications
~~~~~~~~~~~~~

With a multi-cell environment with multiple message queues, it is
likely that operators will want to configure a separate connection to
a unified queue for notifications. This can be done in the configuration file
of all nodes. Refer to the :oslo.messaging-doc:`oslo.messaging configuration
documentation
<configuration/opts.html#oslo_messaging_notifications.transport_url>` for more
details.

Nova Metadata API service
~~~~~~~~~~~~~~~~~~~~~~~~~

The Nova metadata API service should be global across all cells, and
thus be configured as an API-level service with access to the
``[api_database]/connection`` information. The nova metadata API service must
not be run as a standalone service (e.g. must not be run via the
nova-api-metadata script).

Consoleauth service and console proxies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`As of Rocky`__, the ``nova-consoleauth`` service has been deprecated and cell
databases are used for storing token authorizations. All new consoles will be
supported by the database backend and existing consoles will be reset. Console
proxies must be run per cell because the new console token authorizations are
stored in cell databases.

.. __: https://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/convert-consoles-to-objects.html

Operations Requiring upcalls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you deploy multiple cells with a superconductor as described above,
computes and cell-based conductors will not have the ability to speak
to the scheduler as they are not connected to the same MQ. This is by
design for isolation, but currently the processes are not in place to
implement some features without such connectivity. Thus, anything that
requires a so-called "upcall" will not function. This impacts the
following:

#. Instance reschedules during boot and resize (part 1)

   .. note:: This has been resolved in the Queens release [#]_.

#. Instance affinity reporting from the compute nodes to scheduler
#. The late anti-affinity check during server create and evacuate
#. Querying host aggregates from the cell

   .. note:: This has been resolved in the Rocky release [#]_.

#. Attaching a volume and ``[cinder]/cross_az_attach=False``
#. Instance reschedules during boot and resize (part 2)

The first is simple: if you boot an instance, it gets scheduled to a
compute node, fails, it would normally be re-scheduled to another
node. That requires scheduler intervention and thus it will not work
in Pike with a multi-cell layout. If you do not rely on reschedules
for covering up transient compute-node failures, then this will not
affect you. To ensure you do not make futile attempts at rescheduling,
you should set ``[scheduler]/max_attempts=1`` in ``nova.conf``.

The second two are related. The summary is that some of the facilities
that Nova has for ensuring that affinity/anti-affinity is preserved
between instances does not function in Pike with a multi-cell
layout. If you don't use affinity operations, then this will not
affect you. To make sure you don't make futile attempts at the
affinity check, you should set
``[workarounds]/disable_group_policy_check_upcall=True`` and
``[filter_scheduler]/track_instance_changes=False`` in ``nova.conf``.

The fourth is currently only a problem when performing live migrations
using the XenAPI driver and not specifying ``--block-migrate``. The
driver will attempt to figure out if block migration should be performed
based on source and destination hosts being in the same aggregate. Since
aggregates data has migrated to the API database, the cell conductor will
not be able to access the aggregate information and will fail.

The fifth is a problem because when a volume is attached to an instance
in the *nova-compute* service, and ``[cinder]/cross_az_attach=False`` in
nova.conf, we attempt to look up the availability zone that the instance is
in which includes getting any host aggregates that the ``instance.host`` is in.
Since the aggregates are in the API database and the cell conductor cannot
access that information, so this will fail. In the future this check could be
moved to the *nova-api* service such that the availability zone between the
instance and the volume is checked before we reach the cell, except in the
case of boot from volume where the *nova-compute* service itself creates the
volume and must tell Cinder in which availability zone to create the volume.
Long-term, volume creation during boot from volume should be moved to the
top-level superconductor which would eliminate this AZ up-call check problem.

The sixth is detailed in `bug 1781286`_ and similar to the first issue.
The issue is that servers created without a specific availability zone
will have their AZ calculated during a reschedule based on the alternate host
selected. Determining the AZ for the alternate host requires an "up call" to
the API DB.

.. _bug 1781286: https://bugs.launchpad.net/nova/+bug/1781286

.. [#] https://blueprints.launchpad.net/nova/+spec/efficient-multi-cell-instance-list-and-sort
.. [#] https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/return-alternate-hosts.html
.. [#] https://blueprints.launchpad.net/nova/+spec/live-migration-in-xapi-pool
