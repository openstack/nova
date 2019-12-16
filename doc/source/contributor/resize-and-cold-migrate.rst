=======================
Resize and cold migrate
=======================

The `resize API`_ and `cold migrate API`_ are commonly confused in nova because
the internal `API code`_, `conductor code`_ and `compute code`_ use the same
methods. This document explains some of the differences in what
happens between a resize and cold migrate operation.

For the most part this document describes
:term:`same-cell resize <Same-Cell Resize>`.
For details on :term:`cross-cell resize <Cross-Cell Resize>`, refer to
:doc:`/admin/configuration/cross-cell-resize`.

High level
~~~~~~~~~~

:doc:`Cold migrate </admin/migration>` is an operation performed by an
administrator to power off and move a server from one host to a **different**
host using the **same** flavor. Volumes and network interfaces are disconnected
from the source host and connected on the destination host. The type of file
system between the hosts and image backend determine if the server files and
disks have to be copied. If copy is necessary then root and ephemeral disks are
copied and swap disks are re-created.

:doc:`Resize </user/resize>` is an operation which can be performed by a
non-administrative owner of the server (the user) with a **different** flavor.
The new flavor can change certain aspects of the server such as the number of
CPUS, RAM and disk size. Otherwise for the most part the internal details are
the same as a cold migration.

Scheduling
~~~~~~~~~~

Depending on how the API is configured for
:oslo.config:option:`allow_resize_to_same_host`, the server may be able to be
resized on the current host. *All* compute drivers support *resizing* to the
same host but *only* the vCenter driver supports *cold migrating* to the same
host. Enabling resize to the same host is necessary for features such as
strict affinity server groups where there are more than one server in the same
affinity group.

Starting with `microversion 2.56`_ an administrator can specify a destination
host for the cold migrate operation. Resize does not allow specifying a
destination host.

Flavor
~~~~~~

As noted above, with resize the flavor *must* change and with cold migrate the
flavor *will not* change.

Resource claims
~~~~~~~~~~~~~~~

Both resize and cold migration perform a `resize claim`_ on the destination
node. Historically the resize claim was meant as a safety check on the selected
node to work around race conditions in the scheduler. Since the scheduler
started `atomically claiming`_ VCPU, MEMORY_MB and DISK_GB allocations using
Placement the role of the resize claim has been reduced to detecting the same
conditions but for resources like PCI devices and NUMA topology which, at least
as of the 20.0.0 (Train) release, are not modeled in Placement and as such are
not atomic.

If this claim fails, the operation can be rescheduled to an alternative
host, if there are any. The number of possible alternative hosts is determined
by the :oslo.config:option:`scheduler.max_attempts` configuration option.

Allocations
~~~~~~~~~~~

Since the 16.0.0 (Pike) release, the scheduler uses the `placement service`_
to filter compute nodes (resource providers) based on information in the flavor
and image used to build the server. Once the scheduler runs through its filters
and weighers and picks a host, resource class `allocations`_ are atomically
consumed in placement with the server as the consumer.

During both resize and cold migrate operations, the allocations held by the
server consumer against the source compute node resource provider are `moved`_
to a `migration record`_ and the scheduler will create allocations, held by the
instance consumer, on the selected destination compute node resource provider.
This is commonly referred to as `migration-based allocations`_ which were
introduced in the 17.0.0 (Queens) release.

If the operation is successful and confirmed, the source node allocations held
by the migration record are `dropped`_. If the operation fails or is reverted,
the source compute node resource provider allocations held by the migration
record are `reverted`_ back to the instance consumer and the allocations
against the destination compute node resource provider are dropped.

Summary of differences
~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * -
     - Resize
     - Cold migrate
   * - New flavor
     - Yes
     - No
   * - Authorization (default)
     - Admin or owner (user)

       Policy rule: ``os_compute_api:servers:resize``
     - Admin only

       Policy rule: ``os_compute_api:os-migrate-server:migrate``
   * - Same host
     - Maybe
     - Only vCenter
   * - Can specify target host
     - No
     - Yes (microversion >= 2.56)

Sequence Diagrams
~~~~~~~~~~~~~~~~~

The following diagrams are current as of the 21.0.0 (Ussuri) release.

Resize
------

This is the sequence of calls to get the server to ``VERIFY_RESIZE`` status.

.. seqdiag::

    seqdiag {
        API; Conductor; Scheduler; Source; Destination;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API -> Conductor [label = "cast", note = "resize_instance/migrate_server"];
               Conductor => Scheduler [label = "call", note = "select_destinations"];
               Conductor -> Destination [label = "cast", note = "prep_resize"];
                   Source <- Destination [label = "cast", leftnote = "resize_instance"];
                   Source -> Destination [label = "cast", note = "finish_resize"];
    }

Confirm resize
--------------

This is the sequence of calls when confirming `or deleting`_ a server in
``VERIFY_RESIZE`` status.

Note that in the below diagram, if confirming a resize while deleting a server
the API synchronously calls the source compute service.

.. seqdiag::

    seqdiag {
        API; Source;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API -> Source [label = "cast (or call if deleting)", note = "confirm_resize"];
    }

Revert resize
-------------

This is the sequence of calls when reverting a server in ``VERIFY_RESIZE``
status.

.. seqdiag::

    seqdiag {
        API; Source; Destination;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        API -> Destination [label = "cast", note = "revert_resize"];
               Source <- Destination [label = "cast", leftnote = "finish_revert_resize"];
    }

.. _resize API: https://docs.openstack.org/api-ref/compute/#resize-server-resize-action
.. _cold migrate API: https://docs.openstack.org/api-ref/compute/#migrate-server-migrate-action
.. _API code: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/api.py#L3568
.. _conductor code: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/conductor/manager.py#L297
.. _compute code: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L4445
.. _microversion 2.56: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id52
.. _resize claim: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/resource_tracker.py#L248
.. _atomically claiming: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/scheduler/filter_scheduler.py#L239
.. _moved: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/conductor/tasks/migrate.py#L28
.. _placement service: https://docs.openstack.org/placement/latest/
.. _allocations: https://docs.openstack.org/api-ref/placement/#allocations
.. _migration record: https://docs.openstack.org/api-ref/compute/#migrations-os-migrations
.. _migration-based allocations: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/migration-allocations.html
.. _dropped: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L4048
.. _reverted: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L4233
.. _or deleting: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/api.py#L2135
