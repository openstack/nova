=================
Cross-cell resize
=================

This document describes how to configure nova for cross-cell resize.
For information on :term:`same-cell resize <Same-Cell Resize>`, refer to
:doc:`/admin/configuration/resize`.

Historically resizing and cold migrating a server has been explicitly
`restricted`_ to within the same cell in which the server already exists.
The cross-cell resize feature allows configuring nova to allow resizing
and cold migrating servers across cells.

The full design details are in the `Ussuri spec`_ and there is a `video`_ from
a summit talk with a high-level overview.

.. _restricted: https://opendev.org/openstack/nova/src/tag/20.0.0/nova/conductor/tasks/migrate.py#L164
.. _Ussuri spec: https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/cross-cell-resize.html
.. _video: https://www.openstack.org/videos/summits/denver-2019/whats-new-in-nova-cellsv2

Use case
--------

There are many reasons to use multiple cells in a nova deployment beyond just
scaling the database and message queue. Cells can also be used to shard a
deployment by hardware generation and feature functionality. When sharding by
hardware generation, it would be natural to setup a host aggregate for each
cell and map flavors to the aggregate. Then when it comes time to decommission
old hardware the deployer could provide new flavors and request that users
resize to the new flavors, before some deadline, which under the covers will
migrate their servers to the new cell with newer hardware. Administrators
could also just cold migrate the servers during a maintenance window to the
new cell.

Requirements
------------

To enable cross-cell resize functionality the following conditions must be met.

Minimum compute versions
~~~~~~~~~~~~~~~~~~~~~~~~

All compute services must be upgraded to 21.0.0 (Ussuri) or later and not be
pinned to older RPC API versions in
:oslo.config:option:`upgrade_levels.compute`.

Policy configuration
~~~~~~~~~~~~~~~~~~~~

The policy rule ``compute:servers:resize:cross_cell`` controls who can perform
a cross-cell resize or cold migrate operation. By default the policy disables
the functionality for *all* users. A microversion is not required to opt into
the behavior, just passing the policy check. As such, it is recommended to
start by allowing only certain users to be able to perform a cross-cell resize
or cold migration, for example by setting the rule to ``rule:admin_api`` or
some other rule for test teams but not normal users until you are comfortable
supporting the feature.

Compute driver
~~~~~~~~~~~~~~

There are no special compute driver implementations required to support the
feature, it is built on existing driver interfaces used during resize and
shelve/unshelve. However, only the libvirt compute driver has integration
testing in the ``nova-multi-cell`` CI job.

Networking
~~~~~~~~~~

The networking API must expose the ``Port Bindings Extended`` API extension
which was added in the 13.0.0 (Rocky) release for Neutron.

Notifications
-------------

The types of events and their payloads remain unchanged. The major difference
from same-cell resize is the *publisher_id* may be different in some cases
since some events are sent from the conductor service rather than a compute
service. For example, with same-cell resize the
``instance.resize_revert.start`` notification is sent from the source compute
host in the `finish_revert_resize`_ method but with cross-cell resize that
same notification is sent from the conductor service.

Obviously the actual message queue sending the notifications would be different
for the source and target cells assuming they use separate transports.

.. _finish_revert_resize: https://opendev.org/openstack/nova/src/tag/20.0.0/nova/compute/manager.py#L4326

Instance actions
----------------

The overall instance actions named ``resize``, ``confirmResize`` and
``revertResize`` are the same as same-cell resize. However, the *events* which
make up those actions will be different for cross-cell resize since the event
names are generated based on the compute service methods involved in the
operation and there are different methods involved in a cross-cell resize.
This is important for triage when a cross-cell resize operation fails.

Scheduling
----------

The :ref:`CrossCellWeigher <cross-cell-weigher>` is enabled by default. When a
scheduling request allows selecting compute nodes from another cell the weigher
will by default *prefer* hosts within the source cell over hosts from another
cell. However, this behavior is configurable using the
:oslo.config:option:`filter_scheduler.cross_cell_move_weight_multiplier`
configuration option if, for example, you want to drain old cells when resizing
or cold migrating.

Code flow
---------

The end user experience is meant to not change, i.e. status transitions. A
successfully cross-cell resized server will go to ``VERIFY_RESIZE`` status
and from there the user can either confirm or revert the resized server using
the normal `confirmResize`_ and `revertResize`_ server action APIs.

Under the covers there are some differences from a traditional same-cell
resize:

* There is no inter-compute interaction. Everything is synchronously
  `orchestrated`_ from the (super)conductor service. This uses the
  :oslo.config:option:`long_rpc_timeout` configuration option.

* The orchestration tasks in the (super)conductor service are in charge of
  creating a copy of the instance and its related records in the target cell
  database at the beginning of the operation, deleting them in case of rollback
  or when the resize is confirmed/reverted, and updating the
  ``instance_mappings`` table record in the API database.

* Non-volume-backed servers will have their root disk uploaded to the image
  service as a temporary snapshot image just like during the `shelveOffload`_
  operation. When finishing the resize on the destination host in the target
  cell that snapshot image will be used to spawn the guest and then the
  snapshot image will be deleted.

.. _confirmResize: https://docs.openstack.org/api-ref/compute/#confirm-resized-server-confirmresize-action
.. _revertResize: https://docs.openstack.org/api-ref/compute/#revert-resized-server-revertresize-action
.. _orchestrated: https://opendev.org/openstack/nova/src/branch/master/nova/conductor/tasks/cross_cell_migrate.py
.. _shelveOffload: https://docs.openstack.org/api-ref/compute/#shelf-offload-remove-server-shelveoffload-action

Sequence diagram
----------------

The following diagrams are current as of the 21.0.0 (Ussuri) release.

.. NOTE(mriedem): These diagrams could be more detailed, for example breaking
   down the individual parts of the conductor tasks and the calls made on
   the source and dest compute to the virt driver, cinder and neutron, but
   the diagrams could (1) get really complex and (2) become inaccurate with
   changes over time. If there are particular sub-sequences that should have
   diagrams I would suggest putting those into separate focused diagrams.

Resize
~~~~~~

This is the sequence of calls to get the server to ``VERIFY_RESIZE`` status.

.. seqdiag::

    seqdiag {
        API; Conductor; Scheduler; Source; Destination;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API ->> Conductor [label = "cast", note = "resize_instance/migrate_server"];
        Conductor => Scheduler [label = "MigrationTask", note = "select_destinations"];
        Conductor -> Conductor [label = "TargetDBSetupTask"];
        Conductor => Destination [label = "PrepResizeAtDestTask", note = "prep_snapshot_based_resize_at_dest"];
        Conductor => Source [label = "PrepResizeAtSourceTask", note = "prep_snapshot_based_resize_at_source"];
        Conductor => Destination [label = "FinishResizeAtDestTask", note = "finish_snapshot_based_resize_at_dest"];
        Conductor -> Conductor [label = "FinishResizeAtDestTask", note = "update instance mapping"];
    }

Confirm resize
~~~~~~~~~~~~~~

This is the sequence of calls when confirming `or deleting`_ a server in
``VERIFY_RESIZE`` status.

.. seqdiag::

    seqdiag {
        API; Conductor; Source;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API ->> Conductor [label = "cast (or call if deleting)", note = "confirm_snapshot_based_resize"];

        // separator to indicate everything after this is driven by ConfirmResizeTask
        === ConfirmResizeTask ===

        Conductor => Source [label = "call", note = "confirm_snapshot_based_resize_at_source"];
        Conductor -> Conductor [note = "hard delete source cell instance"];
        Conductor -> Conductor [note = "update target cell instance status"];

    }

.. _or deleting: https://opendev.org/openstack/nova/src/tag/20.0.0/nova/compute/api.py#L2171

Revert resize
~~~~~~~~~~~~~

This is the sequence of calls when reverting a server in ``VERIFY_RESIZE``
status.

.. seqdiag::

    seqdiag {
        API; Conductor; Source; Destination;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API ->> Conductor [label = "cast", note = "revert_snapshot_based_resize"];

        // separator to indicate everything after this is driven by RevertResizeTask
        === RevertResizeTask ===

        Conductor -> Conductor [note = "update records from target to source cell"];
        Conductor -> Conductor [note = "update instance mapping"];
        Conductor => Destination [label = "call", note = "revert_snapshot_based_resize_at_dest"];
        Conductor -> Conductor [note = "hard delete target cell instance"];
        Conductor => Source [label = "call", note = "finish_revert_snapshot_based_resize_at_source"];

    }

Limitations
-----------

These are known to not yet be supported in the code:

* Instances with ports attached that have
  :doc:`bandwidth-aware </admin/ports-with-resource-requests>` resource
  provider allocations.
* Rescheduling to alternative hosts within the same target cell in case the
  primary selected host fails the ``prep_snapshot_based_resize_at_dest`` call.

These may not work since they have not been validated by integration testing:

* Instances with PCI devices attached.
* Instances with a NUMA topology.

Other limitations:

* The config drive associated with the server, if there is one, will be
  re-generated on the destination host in the target cell. Therefore if the
  server was created with `personality files`_ they will be lost. However, this
  is no worse than `evacuating`_ a server that had a config drive when the
  source and destination compute host are not on shared storage or when
  shelve offloading and unshelving a server with a config drive. If necessary,
  the resized server can be rebuilt to regain the personality files.
* The ``_poll_unconfirmed_resizes`` periodic task, which can be
  :oslo.config:option:`configured <resize_confirm_window>` to automatically
  confirm pending resizes on the target host, *might* not support cross-cell
  resizes because doing so would require an :ref:`up-call <upcall>` to the
  API to confirm the resize and cleanup the source cell database.

.. _personality files: https://docs.openstack.org/api-guide/compute/server_concepts.html#server-personality
.. _evacuating: https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action

Troubleshooting
---------------

Timeouts
~~~~~~~~

Configure a :ref:`service user <user_token_timeout>` in case the user token
times out, e.g. during the snapshot and download of a large server image.

If RPC calls are timing out with a ``MessagingTimeout`` error in the logs,
check the :oslo.config:option:`long_rpc_timeout` option to see if it is high
enough though the default value (30 minutes) should be sufficient.

Recovering from failure
~~~~~~~~~~~~~~~~~~~~~~~

The orchestration tasks in conductor that drive the operation are built with
rollbacks so each part of the operation can be rolled back in order if a
subsequent task fails.

The thing to keep in mind is the ``instance_mappings`` record in the API DB
is the authority on where the instance "lives" and that is where the API will
go to show the instance in a ``GET /servers/{server_id}`` call or any action
performed on the server, including deleting it.

So if the resize fails and there is a copy of the instance and its related
records in the target cell, the tasks should automatically delete them but if
not you can hard-delete the records from whichever cell is *not* the one in the
``instance_mappings`` table.

If the instance is in ``ERROR`` status, check the logs in both the source
and destination compute service to see if there is anything that needs to be
manually recovered, for example volume attachments or port bindings, and also
check the (super)conductor service logs. Assuming volume attachments and
port bindings are OK (current and pointing at the correct host), then try hard
rebooting the server to get it back to ``ACTIVE`` status. If that fails, you
may need to `rebuild`_ the server on the source host. Note that the guest's
disks on the source host are not deleted until the resize is confirmed so if
there is an issue prior to confirm or confirm itself fails, the guest disks
should still be available for rebuilding the instance if necessary.

.. _rebuild: https://docs.openstack.org/api-ref/compute/#rebuild-server-rebuild-action
