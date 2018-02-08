======================
Live-migrate instances
======================

Live-migrating an instance means moving its virtual machine to a different
OpenStack Compute server while the instance continues running.  Before starting
a live-migration, review the chapter
:ref:`section_configuring-compute-migrations`. It covers the configuration
settings required to enable live-migration, but also reasons for migrations and
non-live-migration options.

The instructions below cover shared-storage and volume-backed migration.  To
block-migrate instances, add the command-line option
``-block-migrate`` to the :command:`nova live-migration` command,
and ``--block-migration`` to the :command:`openstack server migrate`
command.

.. _section-manual-selection-of-dest:

Manual selection of the destination host
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Obtain the ID of the instance you want to migrate:

   .. code-block:: console

      $ openstack server list

      +--------------------------------------+------+--------+-----------------+------------+
      | ID                                   | Name | Status | Networks        | Image Name |
      +--------------------------------------+------+--------+-----------------+------------+
      | d1df1b5a-70c4-4fed-98b7-423362f2c47c | vm1  | ACTIVE | private=a.b.c.d | ...        |
      | d693db9e-a7cf-45ef-a7c9-b3ecb5f22645 | vm2  | ACTIVE | private=e.f.g.h | ...        |
      +--------------------------------------+------+--------+-----------------+------------+

#. Determine on which host the instance is currently running. In this example,
   ``vm1`` is running on ``HostB``:

   .. code-block:: console

      $ openstack server show d1df1b5a-70c4-4fed-98b7-423362f2c47c

      +----------------------+--------------------------------------+
      | Field                | Value                                |
      +----------------------+--------------------------------------+
      | ...                  | ...                                  |
      | OS-EXT-SRV-ATTR:host | HostB                                |
      | ...                  | ...                                  |
      | addresses            | a.b.c.d                              |
      | flavor               | m1.tiny                              |
      | id                   | d1df1b5a-70c4-4fed-98b7-423362f2c47c |
      | name                 | vm1                                  |
      | status               | ACTIVE                               |
      | ...                  | ...                                  |
      +----------------------+--------------------------------------+

#. Select the compute node the instance will be migrated to. In this example,
   we will migrate the instance to ``HostC``, because ``nova-compute`` is
   running on it:

   .. code-block:: console

      $ openstack compute service list

      +----+------------------+-------+----------+---------+-------+----------------------------+
      | ID | Binary           | Host  | Zone     | Status  | State | Updated At                 |
      +----+------------------+-------+----------+---------+-------+----------------------------+
      |  3 | nova-conductor   | HostA | internal | enabled | up    | 2017-02-18T09:42:29.000000 |
      |  4 | nova-scheduler   | HostA | internal | enabled | up    | 2017-02-18T09:42:26.000000 |
      |  5 | nova-consoleauth | HostA | internal | enabled | up    | 2017-02-18T09:42:29.000000 |
      |  6 | nova-compute     | HostB | nova     | enabled | up    | 2017-02-18T09:42:29.000000 |
      |  7 | nova-compute     | HostC | nova     | enabled | up    | 2017-02-18T09:42:29.000000 |
      +----+------------------+-------+----------+---------+-------+----------------------------+

#. Check that ``HostC`` has enough resources for migration:

   .. code-block:: console

      $ openstack host show HostC

      +-------+------------+-----+-----------+---------+
      | Host  | Project    | CPU | Memory MB | Disk GB |
      +-------+------------+-----+-----------+---------+
      | HostC | (total)    |  16 |     32232 |     878 |
      | HostC | (used_now) |  22 |     21284 |     422 |
      | HostC | (used_max) |  22 |     21284 |     422 |
      | HostC | p1         |  22 |     21284 |     422 |
      | HostC | p2         |  22 |     21284 |     422 |
      +-------+------------+-----+-----------+---------+

   - ``cpu``: Number of CPUs

   - ``memory_mb``: Total amount of memory, in MB

   - ``disk_gb``: Total amount of space for NOVA-INST-DIR/instances, in GB

   In this table, the first row shows the total amount of resources available
   on the physical server. The second line shows the currently used resources.
   The third line shows the maximum used resources. The fourth line and below
   shows the resources available for each project.

#. Migrate the instance:

   .. code-block:: console

      $ openstack server migrate d1df1b5a-70c4-4fed-98b7-423362f2c47c --live HostC

#. Confirm that the instance has been migrated successfully:

   .. code-block:: console

      $ openstack server show d1df1b5a-70c4-4fed-98b7-423362f2c47c

      +----------------------+--------------------------------------+
      | Field                | Value                                |
      +----------------------+--------------------------------------+
      | ...                  | ...                                  |
      | OS-EXT-SRV-ATTR:host | HostC                                |
      | ...                  | ...                                  |
      +----------------------+--------------------------------------+

   If the instance is still running on ``HostB``, the migration failed. The
   ``nova-scheduler`` and ``nova-conductor`` log files on the controller and
   the ``nova-compute`` log file on the source compute host can help pin-point
   the problem.

.. _auto_selection_of_dest:

Automatic selection of the destination host
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To leave the selection of the destination host to the Compute service, use the
nova command-line client.

#. Obtain the instance ID as shown in step 1 of the section
   :ref:`section-manual-selection-of-dest`.

#. Leave out the host selection steps 2, 3, and 4.

#. Migrate the instance:

   .. code-block:: console

      $ nova live-migration d1df1b5a-70c4-4fed-98b7-423362f2c47c

Monitoring the migration
~~~~~~~~~~~~~~~~~~~~~~~~

#. Confirm that the instance is migrating:

   .. code-block:: console

      $ openstack server show d1df1b5a-70c4-4fed-98b7-423362f2c47c

      +----------------------+--------------------------------------+
      | Field                | Value                                |
      +----------------------+--------------------------------------+
      | ...                  | ...                                  |
      | status               | MIGRATING                            |
      | ...                  | ...                                  |
      +----------------------+--------------------------------------+

#. Check progress

   Use the nova command-line client for nova's migration monitoring feature.
   First, obtain the migration ID:

   .. code-block:: console

      $ nova server-migration-list d1df1b5a-70c4-4fed-98b7-423362f2c47c
      +----+-------------+-----------  (...)
      | Id | Source Node | Dest Node | (...)
      +----+-------------+-----------+ (...)
      | 2  | -           | -         | (...)
      +----+-------------+-----------+ (...)

   For readability, most output columns were removed. Only the first column,
   **Id**, is relevant.  In this example, the migration ID is 2. Use this to
   get the migration status.

   .. code-block:: console

      $ nova server-migration-show d1df1b5a-70c4-4fed-98b7-423362f2c47c 2
      +------------------------+--------------------------------------+
      | Property               | Value                                |
      +------------------------+--------------------------------------+
      | created_at             | 2017-03-08T02:53:06.000000           |
      | dest_compute           | controller                           |
      | dest_host              | -                                    |
      | dest_node              | -                                    |
      | disk_processed_bytes   | 0                                    |
      | disk_remaining_bytes   | 0                                    |
      | disk_total_bytes       | 0                                    |
      | id                     | 2                                    |
      | memory_processed_bytes | 65502513                             |
      | memory_remaining_bytes | 786427904                            |
      | memory_total_bytes     | 1091379200                           |
      | server_uuid            | d1df1b5a-70c4-4fed-98b7-423362f2c47c |
      | source_compute         | compute2                             |
      | source_node            | -                                    |
      | status                 | running                              |
      | updated_at             | 2017-03-08T02:53:47.000000           |
      +------------------------+--------------------------------------+

   The output shows that the migration is running. Progress is measured by the
   number of memory bytes that remain to be copied. If this number is not
   decreasing over time, the migration may be unable to complete, and it may be
   aborted by the Compute service.

   .. note::

      The command reports that no disk bytes are processed, even in the event
      of block migration.

What to do when the migration times out
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

During the migration process, the instance may write to a memory page after
that page has been copied to the destination. When that happens, the same page
has to be copied again. The instance may write to memory pages faster than they
can be copied, so that the migration cannot complete.  The Compute service will
cancel it when the ``live_migration_completion_timeout``, a configuration
parameter, is reached.

The following remarks assume the KVM/Libvirt hypervisor.

How to know that the migration timed out
----------------------------------------

To determine that the migration timed out, inspect the ``nova-compute`` log
file on the source host. The following log entry shows that the migration timed
out:

.. code-block:: console

   # grep WARNING.*d1df1b5a-70c4-4fed-98b7-423362f2c47c /var/log/nova/nova-compute.log
   ...
   WARNING nova.virt.libvirt.migration [req-...] [instance: ...]
   live migration not completed after 1800 sec

The Compute service also cancels migrations when the memory copy seems to make
no progress. Ocata disables this feature by default, but it can be enabled
using the configuration parameter ``live_migration_progress_timeout``. Should
this be the case, you may find the following message in the log:

.. code-block:: console

   WARNING nova.virt.libvirt.migration [req-...] [instance: ...]
   live migration stuck for 150 sec

Addressing migration timeouts
-----------------------------

To stop the migration from putting load on infrastructure resources like
network and disks, you may opt to cancel it manually.

.. code-block:: console

   $ nova live-migration-abort INSTANCE_ID MIGRATION_ID

To make live-migration succeed, you have several options:

- **Manually force-complete the migration**

  .. code-block:: console

     $ nova live-migration-force-complete INSTANCE_ID MIGRATION_ID

  The instance is paused until memory copy completes.

  .. caution::

     Since the pause impacts time keeping on the instance and not all
     applications tolerate incorrect time settings, use this approach with
     caution.

- **Enable auto-convergence**

  Auto-convergence is a Libvirt feature. Libvirt detects that the migration is
  unlikely to complete and slows down its CPU until the memory copy process is
  faster than the instance's memory writes.

  To enable auto-convergence, set
  ``live_migration_permit_auto_converge=true`` in ``nova.conf`` and restart
  ``nova-compute``. Do this on all compute hosts.

  .. caution::

     One possible downside of auto-convergence is the slowing down of the
     instance.

- **Enable post-copy**

  This is a Libvirt feature. Libvirt detects that the migration does not
  progress and responds by activating the virtual machine on the destination
  host before all its memory has been copied. Access to missing memory pages
  result in page faults that are satisfied from the source host.

  To enable post-copy, set ``live_migration_permit_post_copy=true`` in
  ``nova.conf`` and restart ``nova-compute``. Do this on all compute hosts.

  When post-copy is enabled, manual force-completion does not pause the
  instance but switches to the post-copy process.

  .. caution::

     Possible downsides:

     - When the network connection between source and destination is
       interrupted, page faults cannot be resolved anymore, and the virtual
       machine is rebooted.

     - Post-copy may lead to an increased page fault rate during migration,
       which can slow the instance down.
