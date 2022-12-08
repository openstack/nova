=============================
Soft Delete and Shadow Tables
=============================

Nova has two unrelated features which are called ``soft delete``:

Soft delete instances that can be restored
------------------------------------------

After an instance delete request, the actual delete is
delayed by a configurable amount of time (config option
:oslo.config:option:`reclaim_instance_interval`).  During the delay,
the instance is marked to be in state ``SOFT_DELETED`` and can be
restored (:command:`openstack server restore`) by an admin in order to
gracefully handle human mistakes. If the instance is not restored during
the configured delay, a periodic job actually deletes the instance.

This feature is optional and by default off.

See also:

- "Delete, Restore" in `API Guide: Server Concepts
  <https://docs.openstack.org/api-guide/compute/server_concepts.html#server-actions>`_
- config reference: :oslo.config:option:`reclaim_instance_interval`

Soft delete database rows to shadow tables
------------------------------------------

At an actual instance delete, no DB record is deleted. Instead the
records are marked as deleted (for example ``instances.deleted``
in Nova cell databases). This preserves historic information
for debugging and audit uses. But it also leads to accumulation
of data in Nova cell DB tables, which may have an effect on
Nova DB performance as documented in `DB prune deleted rows
<https://docs.openstack.org/nova/latest/admin/upgrades.html#concepts>`_.

The records marked as deleted can be cleaned up in multiple stages.
First you can move them to so-called shadow tables (tables with prefix
``shadow_`` in Nova cell databases).  This is called *archiving the
deleted rows*.  Nova does not query shadow tables, therefore data moved
to the shadow tables no longer affect DB performance. However storage
space is still consumed.  Then you can actually delete the information
from the shadow tables.  This is called *DB purge*.

These operations can be performed by nova-manage:

- https://docs.openstack.org/nova/latest/cli/nova-manage.html#db-archive-deleted-rows
- https://docs.openstack.org/nova/latest/cli/nova-manage.html#db-purge

This feature is not optional. Every long-running deployment should
regularly archive and purge the deleted rows. For example via a cron
job to regularly call :program:`nova-manage db archive_deleted_rows` and
:program:`nova-manage db purge`.  The tradeoffs between data retention,
DB performance and storage needs should be considered.

In the Mitaka release there was an agreement between Nova developers that
it's not desirable to provide shadow tables for every table in the Nova
database, `documented in a spec
<https://specs.openstack.org/openstack/nova-specs/specs/mitaka/implemented/no-more-soft-delete.html>`_.

Therefore not all information about an instance is preserved in the shadow
tables. Since then new shadow tables are not introduced.
