===========
nova-manage
===========

.. program:: nova-manage

Synopsis
========

::

  nova-manage <category> [<action> [<options>...]]


Description
===========

:program:`nova-manage` controls cloud computing instances by managing various
admin-only aspects of Nova.

The standard pattern for executing a :program:`nova-manage` command is::

    nova-manage <category> <command> [<args>]

Run without arguments to see a list of available command categories::

    nova-manage

You can also run with a category argument such as ``db`` to see a list of all
commands in that category::

    nova-manage db


Options
=======

These options apply to all commands and may be given in any order, before or
after commands. Individual commands may provide additional options. Options
without an argument can be combined after a single dash.

.. option:: -h, --help

    Show a help message and exit

.. option:: --config-dir <dir>

    Path to a config directory to pull ``*.conf`` files from. This file set is
    sorted, so as to provide a predictable parse order if individual options
    are over-ridden. The set is parsed after the file(s) specified via previous
    :option:`--config-file`, arguments hence over-ridden options in the
    directory take precedence.  This option must be set from the command-line.

.. option:: --config-file <path>

    Path to a config file to use. Multiple config files can be specified, with
    values in later files taking precedence. Defaults to None. This option must
    be set from the command-line.

.. option:: --log-config-append <path>, --log-config <path>, --log_config <path>

    The name of a logging configuration file. This file is appended to any
    existing logging configuration files.  For details about logging
    configuration files, see the Python logging module documentation. Note that
    when logging configuration files are used then all logging configuration is
    set in the configuration file and other logging configuration options are
    ignored (for example, :option:`--log-date-format`).

.. option:: --log-date-format <format>

    Defines the format string for ``%(asctime)s`` in log records. Default:
    None. This option is ignored if :option:`--log-config-append` is set.

.. option:: --log-dir <dir>, --logdir <dir>

    The base directory used for relative log_file paths.
    This option is ignored if :option:`--log-config-append` is set.

.. option:: --log-file PATH, --logfile <path>

    Name of log file to send logging output to.
    If no default is set, logging will go to stderr as defined by use_stderr.
    This option is ignored if :option:`--log-config-append` is set.

.. option:: --syslog-log-facility SYSLOG_LOG_FACILITY

    Syslog facility to receive log lines.
    This option is ignored if :option:`--log-config-append` is set.

.. option:: --use-journal

    Enable journald for logging. If running in a systemd environment you may
    wish to enable journal support.  Doing so will use the journal native
    protocol which includes structured metadata in addition to log
    messages. This option is ignored if :option:`--log-config-append` is
    set.

.. option:: --nouse-journal

    The inverse of :option:`--use-journal`.

.. option:: --use-json

    Use JSON formatting for logging. This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --nouse-json

    The inverse of :option:`--use-json`.

.. option:: --use-syslog

    Use syslog for logging. Existing syslog format is DEPRECATED and will be
    changed later to honor RFC5424.  This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --nouse-syslog

    The inverse of :option:`--use-syslog`.

.. option:: --watch-log-file

    Uses logging handler designed to watch file system.  When log file is moved
    or removed this handler will open a new log file with specified path
    instantaneously. It makes sense only if :option:`--log-file` option is
    specified and Linux platform is used. This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --nowatch-log-file

    The inverse of :option:`--watch-log-file`.

.. option:: --debug, -d

    If enabled, the logging level will be set to ``DEBUG`` instead of the
    default ``INFO`` level.

.. option:: --nodebug

    The inverse of :option:`--debug`.

.. option:: --post-mortem

    Allow post-mortem debugging.

.. option:: --nopost-mortem

    The inverse of :option:`--post-mortem`.

.. option:: --version

    Show program's version number and exit


Database Commands
=================

db version
----------

.. program:: nova-manage db version

.. code-block:: shell

    nova-manage db version

Print the current main database version.

db sync
-------

.. program:: nova-manage db sync

.. code-block:: shell

    nova-manage db sync [--local_cell] [VERSION]

Upgrade the main database schema up to the most recent version or ``VERSION``
if specified. By default, this command will also attempt to upgrade the schema
for the cell0 database if it is mapped.
If :option:`--local_cell` is specified, then only the main database in the
current cell is upgraded. The local database connection is determined by
:oslo.config:option:`database.connection` in the configuration file, passed to
nova-manage using the ``--config-file`` option(s).

Refer to the :program:`nova-manage cells_v2 map_cell0` or
:program:`nova-manage cells_v2 simple_cell_setup` commands for more details on
mapping the cell0 database.

This command should be run **after** :program:`nova-manage api_db sync`.

.. rubric:: Options

.. option:: --local_cell

    Only sync db in the local cell: do not attempt to fan-out to all cells.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Successfully synced database schema.
   * - 1
     - Failed to access cell0.

.. versionchanged:: 20.0.0 (Train)

    Removed support for the legacy ``--version <version>`` argument.

.. versionchanged:: 24.0.0 (Xena)

    Migrated versioning engine to alembic. The optional ``VERSION`` argument is
    now expected to be an alembic-based version. sqlalchemy-migrate-based
    versions will be rejected.

db archive_deleted_rows
-----------------------

.. program:: nova-manage db archive_deleted_rows

.. code-block:: shell

    nova-manage db archive_deleted_rows [--max_rows <rows>] [--verbose]
      [--until-complete] [--before <date>] [--purge] [--all-cells] [--task-log]
      [--sleep]

Move deleted rows from production tables to shadow tables. Note that the
corresponding rows in the ``instance_mappings``, ``request_specs`` and
``instance_group_member`` tables of the API database are purged when
instance records are archived and thus,
:oslo.config:option:`api_database.connection` is required in the config
file.

If automating, this should be run continuously while the result is 1,
stopping at 0, or use the :option:`--until-complete` option.

.. versionchanged:: 24.0.0 (Xena)

    Added :option:`--task-log`, :option:`--sleep` options.

.. rubric:: Options

.. option:: --max_rows <rows>

    Maximum number of deleted rows to archive. Defaults to 1000. Note that this
    number does not include the corresponding rows, if any, that are removed
    from the API database for deleted instances.

.. option:: --before <date>

    Archive rows that have been deleted before ``<date>``. Accepts date strings
    in the default format output by the ``date`` command, as well as
    ``YYYY-MM-DD[HH:mm:ss]``. For example::

        # Purge shadow table rows older than a specific date
        nova-manage db archive_deleted_rows --before 2015-10-21
        # or
        nova-manage db archive_deleted_rows --before "Oct 21 2015"
        # Times are also accepted
        nova-manage db archive_deleted_rows --before "2015-10-21 12:00"

    Note that relative dates (such as ``yesterday``) are not supported
    natively. The ``date`` command can be helpful here::

        # Archive deleted rows more than one month old
        nova-manage db archive_deleted_rows --before "$(date -d 'now - 1 month')"

.. option:: --verbose

    Print how many rows were archived per table.

.. option:: --until-complete

    Run continuously until all deleted rows are archived.
    Use :option:`--max_rows` as a batch size for each iteration.

.. option:: --purge

    Purge all data from shadow tables after archive completes.

.. option:: --all-cells

    Run command across all cells.

.. option:: --task-log

    Also archive ``task_log`` table records. Note that ``task_log`` records are
    never deleted, so archiving them will move all of the ``task_log`` records
    up to now into the shadow tables. It is recommended to also specify the
    :option:`--before` option to avoid races for those consuming ``task_log``
    record data via the `/os-instance_usage_audit_log`__ API (example:
    Telemetry).

    .. __: https://docs.openstack.org/api-ref/compute/#server-usage-audit-log-os-instance-usage-audit-log

.. option:: --sleep

    The amount of time in seconds to sleep between batches when
    :option:`--until-complete` is used. Defaults to 0.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Nothing was archived.
   * - 1
     - Some number of rows were archived.
   * - 2
     - Invalid value for :option:`--max_rows`.
   * - 3
     - No connection to the API database could be established using
       :oslo.config:option:`api_database.connection`.
   * - 4
     - Invalid value for :option:`--before`.
   * - 255
     - An unexpected error occurred.

db purge
--------

.. program:: nova-manage db purge

.. code-block:: shell

    nova-manage db purge [--all] [--before <date>] [--verbose] [--all-cells]

Delete rows from shadow tables. For :option:`--all-cells` to work, the API
database connection information must be configured.

.. versionadded:: 18.0.0 (Rocky)

.. rubric:: Options

.. option:: --all

    Purge all rows in the shadow tables.

.. option:: --before <date>

    Delete archived rows that were deleted from Nova before ``<date>``.
    Accepts date strings in the default format output by the ``date``
    command, as well as ``YYYY-MM-DD[HH:mm:ss]``. For example::

        # Purge shadow table rows deleted before specified date
        nova-manage db purge --before 2015-10-21
        # or
        nova-manage db purge --before "Oct 21 2015"
        # Times are also accepted
        nova-manage db purge --before "2015-10-21 12:00"

    Note that relative dates (such as ``yesterday``) are not supported
    natively. The ``date`` command can be helpful here::

        # Archive deleted rows more than one month old
        nova-manage db purge --before "$(date -d 'now - 1 month')"

.. option:: --verbose

    Print information about purged records.

.. option:: --all-cells

    Run against all cell databases.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Rows were deleted.
   * - 1
     - Required arguments were not provided.
   * - 2
     - Invalid value for :option:`--before`.
   * - 3
     - Nothing was purged.
   * - 4
     - No connection to the API database could be established using
       :oslo.config:option:`api_database.connection`.

db online_data_migrations
-------------------------

.. program:: nova-manage db online_data_migrations

.. code-block:: shell

    nova-manage db online_data_migrations [--max-count <count>]

Perform data migration to update all live data.

This command should be called after upgrading database schema and nova services on
all controller nodes. If it exits with partial updates (exit status 1) it should
be called again, even if some updates initially generated errors, because some updates
may depend on others having completed. If it exits with status 2, intervention is
required to resolve the issue causing remaining updates to fail. It should be
considered successfully completed only when the exit status is 0.

For example::

    $ nova-manage db online_data_migrations
    Running batches of 50 until complete
    2 rows matched query migrate_instances_add_request_spec, 0 migrated
    2 rows matched query populate_queued_for_delete, 2 migrated
    +---------------------------------------------+--------------+-----------+
    |                  Migration                  | Total Needed | Completed |
    +---------------------------------------------+--------------+-----------+
    |         create_incomplete_consumers         |      0       |     0     |
    |      migrate_instances_add_request_spec     |      2       |     0     |
    |       migrate_quota_classes_to_api_db       |      0       |     0     |
    |        migrate_quota_limits_to_api_db       |      0       |     0     |
    |          migration_migrate_to_uuid          |      0       |     0     |
    |     populate_missing_availability_zones     |      0       |     0     |
    |          populate_queued_for_delete         |      2       |     2     |
    |                populate_uuids               |      0       |     0     |
    +---------------------------------------------+--------------+-----------+

In the above example, the ``migrate_instances_add_request_spec`` migration
found two candidate records but did not need to perform any kind of data
migration for either of them. In the case of the
``populate_queued_for_delete`` migration, two candidate records were found
which did require a data migration. Since :option:`--max-count` defaults to 50
and only two records were migrated with no more candidates remaining, the
command completed successfully with exit code 0.

.. versionadded:: 13.0.0 (Mitaka)

.. rubric:: Options

.. option:: --max-count <count>

    Controls the maximum number of objects to migrate in a given call. If not
    specified, migration will occur in batches of 50 until fully complete.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - No (further) updates are possible.
   * - 1
     - Some updates were completed successfully. Note that not all updates may
       have succeeded.
   * - 2
     - Some updates generated errors and no other migrations were able to take
       effect in the last batch attempted.
   * - 127
     - Invalid input was provided.

db ironic_compute_node_move
---------------------------

.. program:: nova-manage db ironic_compute_node_move

.. code-block:: shell

    nova-manage db ironic_compute_node_move --ironic-node-uuid <uuid> --destination-host <host>

Move ironic nodes, along with any associated instances,
between nova-compute services.

This is useful when migrating away from using peer_list and multiple
hash ring balanced nova-compute servers to the new ironic shard system.

First you must turn off the nova-compute service that currently manages
the Ironic host. Second you mark that nova-compute service as forced down
via the Nova API. Third, you ensure the new nova-compute service is
correctly configured to target the appropriate shard (and optionally
also a conductor group). Finally, most Ironic nodes should now move to
the new service, but any Ironic nodes with instances on them
will need to be manually moved to their new Ironic service
by using this nova-manage command.

.. versionadded:: 28.0.0 (2023.2 Bobcat)

.. rubric:: Options

.. option:: --ironic-node-uuid <uuid>

    Ironic node uuid to be moved (which is also the Nova compute node uuid
    and the uuid of corresponding resource provider in Placement).

    The Nova compute service that currently manages this Ironic node
    must first be marked a "forced down" via the Nova API, in a similar
    way to a down hypervisor that is about to have its VMs evacuated to
    a replacement hypervisor.

.. option:: --destination-host <host>

    Destination ironic nova-compute service CONF.host.

API Database Commands
=====================

api_db version
--------------

.. program:: nova-manage api_db version

.. code-block:: shell

    nova-manage api_db version

Print the current API database version.

.. versionadded:: 2015.1.0 (Kilo)

api_db sync
-----------

.. program:: nova-manage api_db sync

.. code-block:: shell

    nova-manage api_db sync [VERSION]

Upgrade the API database schema up to the most recent version or
``VERSION`` if specified. This command does not create the API
database, it runs schema migration scripts. The API database connection is
determined by :oslo.config:option:`api_database.connection` in the
configuration file passed to nova-manage.

This command should be run before ``nova-manage db sync``.

.. versionadded:: 2015.1.0 (Kilo)

.. versionchanged:: 18.0.0 (Rocky)

    Added support for upgrading the optional placement database if
    ``[placement_database]/connection`` is configured.

.. versionchanged:: 20.0.0 (Train)

    Removed support for upgrading the optional placement database as placement
    is now a separate project.

    Removed support for the legacy ``--version <version>`` argument.

.. versionchanged:: 24.0.0 (Xena)

    Migrated versioning engine to alembic. The optional ``VERSION`` argument is
    now expected to be an alembic-based version. sqlalchemy-migrate-based
    versions will be rejected.

.. _man-page-cells-v2:


Cells v2 Commands
=================

cell_v2 simple_cell_setup
-------------------------

.. program:: nova-manage cell_v2 simple_cell_setup

.. code-block:: shell

    nova-manage cell_v2 simple_cell_setup [--transport-url <transport_url>]

Setup a fresh cells v2 environment. If :option:`--transport-url` is not
specified, it will use the one defined by :oslo.config:option:`transport_url`
in the configuration file.

.. versionadded:: 14.0.0 (Newton)

.. rubric:: Options

.. option:: --transport-url <transport_url>

    The transport url for the cell message queue.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Setup is completed.
   * - 1
     - No hosts are reporting, meaning none can be mapped, or if the transport
       URL is missing or invalid.

cell_v2 map_cell0
-----------------

.. program:: nova-manage cell_v2 map_cell0

.. code-block:: shell

    nova-manage cell_v2 map_cell0 [--database_connection <database_connection>]

Create a cell mapping to the database connection for the cell0 database.
If a database_connection is not specified, it will use the one defined by
:oslo.config:option:`database.connection` in the configuration file passed
to nova-manage. The cell0 database is used for instances that have not been
scheduled to any cell. This generally applies to instances that have
encountered an error before they have been scheduled.

.. versionadded:: 14.0.0 (Newton)

.. rubric:: Options

.. option:: --database_connection <database_connection>

    The database connection URL for ``cell0``. This is optional. If not
    provided, a standard database connection will be used based on the main
    database connection from nova configuration.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - ``cell0`` is created successfully or has already been set up.

cell_v2 map_instances
---------------------

.. program:: nova-manage cell_v2 map_instances

.. code-block:: shell

    nova-manage cell_v2 map_instances --cell_uuid <cell_uuid>
      [--max-count <max_count>] [--reset]

Map instances to the provided cell. Instances in the nova database will
be queried from oldest to newest and mapped to the provided cell.
A :option:`--max-count` can be set on the number of instance to map in a single
run. Repeated runs of the command will start from where the last run finished
so it is not necessary to increase :option:`--max-count` to finish.
A :option:`--reset` option can be passed which will reset the marker, thus
making the command start from the beginning as opposed to the default behavior
of starting from where the last run finished.

If :option:`--max-count` is not specified, all instances in the cell will be
mapped in batches of 50. If you have a large number of instances, consider
specifying a custom value and run the command until it exits with 0.

.. versionadded:: 12.0.0 (Liberty)

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    Unmigrated instances will be mapped to the cell with the UUID provided.

.. option:: --max-count <max_count>

    Maximum number of instances to map. If not set, all instances in the cell
    will be mapped in batches of 50. If you have a large number of instances,
    consider specifying a custom value and run the command until it exits with
    0.

.. option:: --reset

    The command will start from the beginning as opposed to the default
    behavior of starting from where the last run finished.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - All instances have been mapped.
   * - 1
     - There are still instances to be mapped.
   * - 127
     - Invalid value for :option:`--max-count`.
   * - 255
     - An unexpected error occurred.

cell_v2 map_cell_and_hosts
--------------------------

.. program:: nova-manage cell_v2 map_cell_and_hosts

.. code-block:: shell

    nova-manage cell_v2 map_cell_and_hosts [--name <cell_name>]
      [--transport-url <transport_url>] [--verbose]

Create a cell mapping to the database connection and message queue
transport URL, and map hosts to that cell. The database connection
comes from the :oslo.config:option:`database.connection` defined in the
configuration file passed to nova-manage. If :option:`--transport-url` is not
specified, it will use the one defined by
:oslo.config:option:`transport_url` in the configuration file. This command
is idempotent (can be run multiple times), and the verbose option will
print out the resulting cell mapping UUID.

.. versionadded:: 13.0.0 (Mitaka)

.. rubric:: Options

.. option:: --transport-url <transport_url>

    The transport url for the cell message queue.

.. option:: --name <cell_name>

    The name of the cell.

.. option:: --verbose

    Output the cell mapping uuid for any newly mapped hosts.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Successful completion.
   * - 1
     - The transport url is missing or invalid

cell_v2 verify_instance
-----------------------

.. program:: nova-manage cell_v2 verify_instance

.. code-block:: shell

    nova-manage cell_v2 verify_instance --uuid <instance_uuid> [--quiet]

Verify instance mapping to a cell. This command is useful to determine if
the cells v2 environment is properly setup, specifically in terms of the
cell, host, and instance mapping records required.

.. versionadded:: 14.0.0 (Newton)

.. rubric:: Options

.. option:: --uuid <instance_uuid>

    The instance UUID to verify.

.. option:: --quiet

    Do not print anything.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - The instance was successfully mapped to a cell.
   * - 1
     - The instance is not mapped to a cell. See the ``map_instances``
       command.
   * - 2
     - The cell mapping is missing. See the ``map_cell_and_hots`` command if
       you are upgrading from a cells v1 environment, and the
       ``simple_cell_setup`` command if you are upgrading from a non-cells v1
       environment.
   * - 3
     - The instance is a deleted instance that still has an instance mapping.
   * - 4
     - The instance is an archived instance that still has an instance mapping.

cell_v2 create_cell
-------------------

.. program:: nova-manage cell_v2 create_cell

.. code-block:: shell

    nova-manage cell_v2 create_cell [--name <cell_name>]
      [--transport-url <transport_url>]
      [--database_connection <database_connection>] [--verbose] [--disabled]

Create a cell mapping to the database connection and message queue
transport URL. If a database_connection is not specified, it will use the
one defined by :oslo.config:option:`database.connection` in the
configuration file passed to nova-manage. If :option:`--transport-url` is not
specified, it will use the one defined by
:oslo.config:option:`transport_url` in the configuration file. The verbose
option will print out the resulting cell mapping UUID. All the cells
created are by default enabled. However passing the :option:`--disabled` option
can create a pre-disabled cell, meaning no scheduling will happen to this
cell.

.. versionadded:: 15.0.0 (Ocata)

.. versionchanged:: 18.0.0 (Rocky)

    Added :option:`--disabled` option.

.. rubric:: Options

.. option:: --name <cell_name>

    The name of the cell.

.. option:: --database_connection <database_connection>

    The database URL for the cell database.

.. option:: --transport-url <transport_url>

    The transport url for the cell message queue.

.. option:: --verbose

    Output the UUID of the created cell.

.. option:: --disabled

    Create a pre-disabled cell.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - The cell mapping was successfully created.
   * - 1
     - The transport URL or database connection was missing or invalid.
   * - 2
     - Another cell is already using the provided transport URL and/or database
       connection combination.

cell_v2 discover_hosts
----------------------

.. program:: nova-manage cell_v2 discover_hosts

.. code-block:: shell

    nova-manage cell_v2 discover_hosts [--cell_uuid <cell_uuid>] [--verbose]
      [--strict] [--by-service]

Searches cells, or a single cell, and maps found hosts. This command will
check the database for each cell (or a single one if passed in) and map any
hosts which are not currently mapped. If a host is already mapped, nothing
will be done. You need to re-run this command each time you add a batch of
compute hosts to a cell (otherwise the scheduler will never place instances
there and the API will not list the new hosts). If :option:`--strict` is
specified, the command will only return 0 if an unmapped host was discovered
and mapped successfully. If :option:`--by-service` is specified, this command will
look in the appropriate cell(s) for any nova-compute services and ensure there
are host mappings for them. This is less efficient and is only necessary
when using compute drivers that may manage zero or more actual compute
nodes at any given time (currently only ironic).

This command should be run once after all compute hosts have been deployed
and should not be run in parallel. When run in parallel, the commands will
collide with each other trying to map the same hosts in the database at the
same time.

.. versionadded:: 14.0.0 (Newton)

.. versionchanged:: 16.0.0 (Pike)

    Added :option:`--strict` option.

.. versionchanged:: 18.0.0 (Rocky)

    Added :option:`--by-service` option.

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    If provided only this cell will be searched for new hosts to map.

.. option:: --verbose

    Provide detailed output when discovering hosts.

.. option:: --strict

    Considered successful (exit code 0) only when an unmapped host is
    discovered. Any other outcome will be considered a failure (non-zero exit
    code).

.. option:: --by-service

    Discover hosts by service instead of compute node.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Hosts were successfully mapped or no hosts needed to be mapped. If
       :option:`--strict` is specified, returns 0 only if an unmapped host was
       discovered and mapped.
   * - 1
     - If :option:`--strict` is specified and no unmapped hosts were found.
       Also returns 1 if an exception was raised while running.
   * - 2
     - The command was aborted because of a duplicate host mapping found. This
       means the command collided with another running ``discover_hosts``
       command or scheduler periodic task and is safe to retry.

cell_v2 list_cells
------------------

.. program:: nova-manage cell_v2 list_cells

.. code-block:: shell

    nova-manage cell_v2 list_cells [--verbose]

By default the cell name, UUID, disabled state, masked transport URL and
database connection details are shown. Use the :option:`--verbose` option to
see transport URL and database connection with their sensitive details.

.. versionadded:: 15.0.0 (Ocata)

.. versionchanged:: 18.0.0 (Rocky)

    Added the ``disabled`` column to output.

.. rubric:: Options

.. option:: --verbose

    Show sensitive details, such as passwords.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success.

cell_v2 delete_cell
-------------------

.. program:: nova-manage cell_v2 delete_cell

.. code-block:: shell

    nova-manage cell_v2 delete_cell [--force] --cell_uuid <cell_uuid>

Delete a cell by the given UUID.

.. versionadded:: 15.0.0 (Ocata)

.. rubric:: Options

.. option:: --force

    Delete hosts and instance_mappings that belong to the cell as well.

.. option:: --cell_uuid <cell_uuid>

    The UUID of the cell to delete.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - An empty cell was found and deleted successfully or a cell that has
       hosts was found and the cell, hosts and the instance_mappings were
       deleted successfully with :option:`--force` option (this happens if there are
       no living instances).
   * - 1
     - A cell with the provided UUID could not be found.
   * - 2
     - Host mappings were found for the cell, meaning the cell is not empty,
       and the :option:`--force` option was not provided.
   * - 3
     - There are active instances mapped to the cell (cell not empty).
   * - 4
     - There are (inactive) instances mapped to the cell and the
       :option:`--force` option was not provided.

cell_v2 list_hosts
------------------

.. program:: nova-manage cell_v2 list_hosts

.. code-block:: shell

    nova-manage cell_v2 list_hosts [--cell_uuid <cell_uuid>]

Lists the hosts in one or all v2 cells. By default hosts in all v2 cells
are listed. Use the :option:`--cell_uuid` option to list hosts in a specific cell.

.. versionadded:: 17.0.0 (Queens)

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    The UUID of the cell.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success.
   * - 1
     - The cell indicated by :option:`--cell_uuid` was not found.

cell_v2 update_cell
-------------------

.. program:: nova-manage cell_v2 update_cell

.. code-block:: shell

    nova-manage cell_v2 update_cell --cell_uuid <cell_uuid>
      [--name <cell_name>] [--transport-url <transport_url>]
      [--database_connection <database_connection>] [--disable] [--enable]

Updates the properties of a cell by the given uuid. If a
database_connection is not specified, it will attempt to use the one
defined by :oslo.config:option:`database.connection` in the configuration
file. If a transport_url is not specified, it will attempt to use the one
defined by :oslo.config:option:`transport_url` in the configuration file.

.. note::

    Updating the ``transport_url`` or ``database_connection`` fields on a
    running system will NOT result in all nodes immediately using the new
    values.  Use caution when changing these values.

    The scheduler will not notice that a cell has been enabled/disabled until
    it is restarted or sent the SIGHUP signal.

.. versionadded:: 16.0.0 (Pike)

.. versionchanged:: 18.0.0 (Rocky)

    Added :option:`--enable`, :option:`--disable` options.

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    The UUID of the cell to update.

.. option:: --name <cell_name>

    Set the cell name.

.. option:: --transport-url <transport_url>

    Set the cell ``transport_url``. Note that running nodes will not see
    the change until restarted or the ``SIGHUP`` signal is sent.

.. option:: --database_connection <database_connection>

    Set the cell ``database_connection``. Note that running nodes will not see
    the change until restarted or the ``SIGHUP`` signal is sent.

.. option:: --disable

    Disables the cell. Note that the scheduling will be blocked to this cell
    until it is enabled and the ``nova-scheduler`` service is restarted or
    the ``SIGHUP`` signal is sent.

.. option:: --enable

    Enables the cell. Note that the ``nova-scheduler`` service will not see the
    change until it is restarted or the ``SIGHUP`` signal is sent.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success.
   * - 1
     - The cell was not found by the provided UUID.
   * - 2
     - The specified properties could not be set.
   * - 3
     - The provided :option:`--transport-url` or/and
       :option:`--database_connection` parameters were same as another cell.
   * - 4
     - An attempt was made to disable and enable a cell at the same time.
   * - 5
     - An attempt was made to disable or enable cell0.

cell_v2 delete_host
-------------------

.. program:: nova-manage cell_v2 delete_host

.. code-block:: shell

    nova-manage cell_v2 delete_host --cell_uuid <cell_uuid> --host <host>

Delete a host by the given host name and the given cell UUID.

.. versionadded:: 17.0.0 (Queens)

.. note::

    The scheduler caches host-to-cell mapping information so when deleting
    a host the scheduler may need to be restarted or sent the SIGHUP signal.

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    The UUID of the cell.

.. option:: --host <host>

    The host to delete.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - The empty host was found and deleted successfully
   * - 1
     - A cell with the specified UUID could not be found.
   * - 2
     - A host with the specified name could not be found
   * - 3
     - The host with the specified name is not in a cell with the specified UUID.
   * - 4
     - The host with the specified name has instances (host not empty).


Placement Commands
==================

.. _heal_allocations_cli:

placement heal_allocations
--------------------------

.. program:: nova-manage placement heal_allocations

.. code-block:: shell

    nova-manage placement heal_allocations [--max-count <max_count>]
      [--verbose] [--skip-port-allocations] [--dry-run]
      [--instance <instance_uuid>] [--cell <cell_uuid] [--force]

Iterates over non-cell0 cells looking for instances which do not have
allocations in the Placement service and which are not undergoing a task
state transition. For each instance found, allocations are created against
the compute node resource provider for that instance based on the flavor
associated with the instance.

.. note::
    Nested allocations are only partially supported. Nested allocations due to
    Neutron ports having QoS policies are supported since 20.0.0 (Train)
    release. But nested allocations due to vGPU or Cyborg device profile
    requests in the flavor are not supported. Also if you are using
    provider.yaml files on compute hosts to define additional resources, if
    those resources are defined on child resource providers then instances
    using such resources are not supported.

Also if the instance has any port attached that has resource request
(e.g. :neutron-doc:`Quality of Service (QoS): Guaranteed Bandwidth
<admin/config-qos-min-bw.html>`) but the corresponding
allocation is not found then the allocation is created against the
network device resource providers according to the resource request of
that port. It is possible that the missing allocation cannot be created
either due to not having enough resource inventory on the host the instance
resides on or because more than one resource provider could fulfill the
request. In this case the instance needs to be manually deleted or the
port needs to be detached. When nova `supports migrating instances
with guaranteed bandwidth ports`__, migration will heal missing allocations
for these instances.

.. __: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/support-move-ops-with-qos-ports.html

Before the allocations for the ports are persisted in placement nova-manage
tries to update each port in neutron to refer to the resource provider UUID
which provides the requested resources. If any of the port updates fail in
neutron or the allocation update fails in placement the command tries to
roll back the partial updates to the ports. If the roll back fails
then the process stops with exit code ``7`` and the admin needs to do the
rollback in neutron manually according to the description in the exit code
section.

There is also a special case handled for instances that *do* have
allocations created before Placement API microversion 1.8 where project_id
and user_id values were required. For those types of allocations, the
project_id and user_id are updated using the values from the instance.

This command requires that the
:oslo.config:option:`api_database.connection` and
:oslo.config:group:`placement` configuration options are set. Placement API
>= 1.28 is required.

.. versionadded:: 18.0.0 (Rocky)

.. versionchanged:: 20.0.0 (Train)

    Added :option:`--dry-run`, :option:`--instance`, and
    :option:`--skip-port-allocations` options.

.. versionchanged:: 21.0.0 (Ussuri)

    Added :option:`--cell` option.

.. versionchanged:: 22.0.0 (Victoria)

    Added :option:`--force` option.

.. versionchanged:: 25.0.0 (Yoga)

    Added support for healing port allocations if port-resource-request-groups
    neutron API extension is enabled and therefore ports can request multiple
    group of resources e.g. by using both guaranteed minimum bandwidth and
    guaranteed minimum packet rate QoS policy rules.

.. rubric:: Options

.. option:: --max-count <max_count>

    Maximum number of instances to process. If not specified, all instances in
    each cell will be mapped in batches of 50. If you have a large number of
    instances, consider specifying a custom value and run the command until it
    exits with 0 or 4.

.. option:: --verbose

    Provide verbose output during execution.

.. option:: --dry-run

    Runs the command and prints output but does not commit any changes. The
    return code should be 4.

.. option::  --instance <instance_uuid>

    UUID of a specific instance to process. If specified :option:`--max-count`
    has no effect. Mutually exclusive with :option:`--cell`.

.. option:: --skip-port-allocations

    Skip the healing of the resource allocations of bound ports. E.g. healing
    bandwidth resource allocation for ports having minimum QoS policy rules
    attached. If your deployment does not use such a feature then the
    performance impact of querying neutron ports for each instance can be
    avoided with this flag.

.. option:: --cell <cell_uuid>

    Heal allocations within a specific cell. Mutually exclusive with
    :option:`--instance`.

.. option:: --force

    Force heal allocations. Requires the :option:`--instance` argument.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Command completed successfully and allocations were created.
   * - 1
     - :option:`--max-count` was reached and there are more instances to
       process.
   * - 2
     - Unable to find a compute node record for a given instance.
   * - 3
     - Unable to create (or update) allocations for an instance against its
       compute node resource provider.
   * - 4
     - Command completed successfully but no allocations were created.
   * - 5
     - Unable to query ports from neutron
   * - 6
     - Unable to update ports in neutron
   * - 7
     - Cannot roll back neutron port updates. Manual steps needed. The
       error message will indicate which neutron ports need to be changed
       to clean up ``binding:profile`` of the port::

         $ openstack port unset <port_uuid> --binding-profile allocation

   * - 127
     - Invalid input.
   * - 255
     - An unexpected error occurred.

.. _sync_aggregates_cli:

placement sync_aggregates
-------------------------

.. program:: nova-manage placement sync_aggregates

.. code-block:: shell

    nova-manage placement sync_aggregates [--verbose]

Mirrors compute host aggregates to resource provider aggregates
in the Placement service. Requires the :oslo.config:group:`api_database`
and :oslo.config:group:`placement` sections of the nova configuration file
to be populated.

Specify :option:`--verbose` to get detailed progress output during execution.

.. note::

    Depending on the size of your deployment and the number of
    compute hosts in aggregates, this command could cause a non-negligible
    amount of traffic to the placement service and therefore is
    recommended to be run during maintenance windows.

.. versionadded:: 18.0.0 (Rocky)

.. rubric:: Options

.. option:: --verbose

    Provide verbose output during execution.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Successful run
   * - 1
     - A host was found with more than one matching compute node record
   * - 2
     - An unexpected error occurred while working with the placement API
   * - 3
     - Failed updating provider aggregates in placement
   * - 4
     - Host mappings not found for one or more host aggregate members
   * - 5
     - Compute node records not found for one or more hosts
   * - 6
     - Resource provider not found by uuid for a given host
   * - 255
     - An unexpected error occurred.

.. _placement_audit_cli:

placement audit
---------------

.. program:: nova-manage placement audit

.. code-block:: shell

    nova-manage placement audit [--verbose] [--delete]
      [--resource_provider <uuid>]

Iterates over all the Resource Providers (or just one if you provide the
UUID) and then verifies if the compute allocations are either related to
an existing instance or a migration UUID. If not, it will tell which
allocations are orphaned.

This command requires that the
:oslo.config:option:`api_database.connection` and
:oslo.config:group:`placement` configuration options are set. Placement API
>= 1.14 is required.

.. versionadded:: 21.0.0 (Ussuri)

.. rubric:: Options

.. option:: --verbose

    Provide verbose output during execution.

.. option:: --resource_provider <provider_uuid>

    UUID of a specific resource provider to verify.

.. option:: --delete

    Deletes orphaned allocations that were found.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - No orphaned allocations were found
   * - 1
     - An unexpected error occurred
   * - 3
     - Orphaned allocations were found
   * - 4
     - All found orphaned allocations were deleted
   * - 127
     - Invalid input


Volume Attachment Commands
==========================

volume_attachment get_connector
-------------------------------

.. program:: nova-manage volume_attachment get_connector

.. code-block:: shell

    nova-manage volume_attachment get_connector

Show the host connector for this compute host.

When called with the ``--json`` switch this dumps a JSON string containing the
connector information for the current host, which can be saved to a file and
used as input for the :program:`nova-manage volume_attachment refresh` command.

.. versionadded:: 24.0.0 (Xena)

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success
   * - 1
     - An unexpected error occurred

volume_attachment show
----------------------

.. program:: nova-manage volume_attachment show

.. code-block:: shell

    nova-manage volume_attachment show [INSTANCE_UUID] [VOLUME_ID]

Show the details of a the volume attachment between ``VOLUME_ID`` and
``INSTANCE_UUID``.

.. versionadded:: 24.0.0 (Xena)

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success
   * - 1
     - An unexpected error occurred
   * - 2
     - Instance not found
   * - 3
     - Instance is not attached to volume

volume_attachment refresh
-------------------------

.. program:: nova-manage volume_attachment refresh

.. code-block:: shell

    nova-manage volume_attachment refresh [INSTANCE_UUID] [VOLUME_ID] [CONNECTOR_PATH]

Refresh the connection info associated with a given volume attachment.

The instance must be attached to the volume, have a ``vm_state`` of ``stopped``
and not be ``locked``.

``CONNECTOR_PATH`` should be the path to a JSON-formatted file containing up to
date connector information for the compute currently hosting the instance as
generated using the :program:`nova-manage volume_attachment get_connector`
command.

.. versionadded:: 24.0.0 (Xena)

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Success
   * - 1
     - An unexpected error occurred
   * - 2
     - Connector path does not exist
   * - 3
     - Failed to open connector path
   * - 4
     - Instance does not exist
   * - 5
     - Instance state invalid (must be stopped and unlocked)
   * - 6
     - Volume is not attached to the instance
   * - 7
     - Connector host is not correct


Libvirt Commands
================

libvirt get_machine_type
------------------------

.. program:: nova-manage libvirt get_machine_type

.. code-block:: shell

    nova-manage libvirt get_machine_type [INSTANCE_UUID]

Fetch and display the recorded machine type of a libvirt instance identified
by ``INSTANCE_UUID``.

.. versionadded:: 23.0.0 (Wallaby)

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Successfully completed
   * - 1
     - An unexpected error occurred
   * - 2
     - Unable to find instance or instance mapping
   * - 3
     - No machine type found for instance

libvirt update_machine_type
---------------------------

.. program:: nova-manage libvirt update_machine_type

.. code-block:: shell

    nova-manage libvirt update_machine_type \
        [INSTANCE_UUID] [MACHINE_TYPE] [--force]

Set or update the recorded machine type of instance ``INSTANCE_UUID`` to
machine type ``MACHINE_TYPE``.

The following criteria must be met when using this command:

* The instance must have a ``vm_state`` of ``STOPPED``, ``SHELVED`` or
  ``SHELVED_OFFLOADED``.

* The machine type must be supported. The supported list includes alias and
  versioned types of ``pc``, ``pc-i440fx``, ``pc-q35``, ``q35``, ``virt``
  or ``s390-ccw-virtio``.

* The update will not move the instance between underlying machine types.
  For example, ``pc`` to ``q35``.

* The update will not move the instance between an alias and versioned
  machine type or vice versa. For example, ``pc`` to ``pc-1.2.3`` or
  ``pc-1.2.3`` to ``pc``.

A ``--force`` flag is provided to skip the above checks but caution
should be taken as this could easily lead to the underlying ABI of the
instance changing when moving between machine types.

.. versionadded:: 23.0.0 (Wallaby)

.. rubric:: Options

.. option:: --force

    Skip machine type compatibility checks and force machine type update.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Update completed successfully
   * - 1
     - An unexpected error occurred
   * - 2
     - Unable to find instance or instance mapping
   * - 3
     - The instance has an invalid ``vm_state``
   * - 4
     - The proposed update of the machine type is invalid
   * - 5
     - The provided machine type is unsupported

libvirt list_unset_machine_type
-------------------------------

.. program:: nova-manage libvirt list_unset_machine_type

.. code-block:: shell

    nova-manage libvirt list_unset_machine_type [--cell-uuid <cell-uuid>]

List the UUID of any instance without ``hw_machine_type`` set.

This command is useful for operators attempting to determine when it is
safe to change the :oslo.config:option:`libvirt.hw_machine_type` option
within an environment.

.. versionadded:: 23.0.0 (Wallaby)

.. rubric:: Options

.. option:: --cell_uuid <cell_uuid>

    The UUID of the cell to list instances from.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Completed successfully, no instances found without ``hw_machine_type``
       set
   * - 1
     - An unexpected error occurred
   * - 2
     - Unable to find cell mapping
   * - 3
     - Instances found without ``hw_machine_type`` set


Image Property Commands
=======================

image_property show
-------------------

.. program:: nova-manage image_property show

.. code-block:: shell

    nova-manage image_property show [INSTANCE_UUID] [IMAGE_PROPERTY]

Fetch and display the recorded image property ``IMAGE_PROPERTY`` of an
instance identified by ``INSTANCE_UUID``.

.. versionadded:: 25.0.0 (Yoga)

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Successfully completed
   * - 1
     - An unexpected error occurred
   * - 2
     - Unable to find instance or instance mapping
   * - 3
     - No image property found for instance

image_property set
------------------

.. program:: nova-manage image_property set

.. code-block:: shell

    nova-manage image_property set \
        [INSTANCE_UUID] [--property] [IMAGE_PROPERTY]=[VALUE]

Set or update the recorded image property ``IMAGE_PROPERTY`` of instance
``INSTANCE_UUID`` to value ``VALUE``.

The following criteria must be met when using this command:

* The instance must have a ``vm_state`` of ``STOPPED``, ``SHELVED`` or
  ``SHELVED_OFFLOADED``.

This command is useful for operators who need to update stored instance image
properties that have become invalidated by a change of instance machine type,
for example.

.. versionadded:: 25.0.0 (Yoga)

.. rubric:: Options

.. option:: --property

    Image property to set using the format name=value. For example:
    ``--property hw_disk_bus=virtio --property hw_cdrom_bus=sata``.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Update completed successfully
   * - 1
     - An unexpected error occurred
   * - 2
     - Unable to find instance or instance mapping
   * - 3
     - The instance has an invalid ``vm_state``
   * - 4
     - The provided image property name is invalid
   * - 5
     - The provided image property value is invalid


Limits Commands
===============

limits migrate_to_unified_limits
--------------------------------

.. program:: nova-manage limits migrate_to_unified_limits

.. code-block:: shell

   nova-manage limits migrate_to_unified_limits [--project-id <project-id>]
   [--region-id <region-id>] [--verbose] [--dry-run]

Migrate quota limits from the Nova database to unified limits in Keystone.

This command is useful for operators to migrate from legacy quotas to unified
limits. Limits are migrated by copying them from the Nova database to Keystone
by creating them using the Keystone API.

The Nova configuration file used by ``nova-manage`` must have a ``[keystone]``
section that contains authentication settings in order for the Keystone API
calls to succeed. As an example:

.. code-block:: ini

   [keystone]
   region_name = RegionOne
   user_domain_name = Default
   auth_url = http://127.0.0.1/identity
   auth_type = password
   username = admin
   password = <password>
   system_scope = all

By default `Keystone policy configuration`_, access to create, update, and
delete in the `unified limits API`_ is restricted to callers with
`system-scoped authorization tokens`_. The ``system_scope = all`` setting
indicates the scope for system operations. You will need to ensure that the
user configured under ``[keystone]`` has the necessary role and scope.

.. warning::

   The ``limits migrate_to_unified_limits`` command will create limits only
   for resources that exist in the legacy quota system and any resource that
   does not have a unified limit in Keystone will use a quota limit of **0**.

   For resource classes that are allocated by the placement service and have no
   default limit set, you will need to create default limits manually. The most
   common example is class:DISK_GB. All Nova API requests that need to allocate
   DISK_GB will fail quota enforcement until a default limit for it is set in
   Keystone.

   See the :doc:`unified limits documentation
   </admin/unified-limits>` about creating limits using the OpenStackClient.

.. _Keystone policy configuration: https://docs.openstack.org/keystone/latest/configuration/policy.html
.. _unified limits API: https://docs.openstack.org/api-ref/identity/v3/index.html#unified-limits
.. _system-scoped authorization tokens: https://docs.openstack.org/keystone/latest/admin/tokens-overview.html#system-scoped-tokens

.. versionadded:: 28.0.0 (2023.2 Bobcat)

.. rubric:: Options

.. option:: --project-id <project-id>

    The project ID for which to migrate quota limits.

.. option:: --region-id <region-id>

    The region ID for which to migrate quota limits.

.. option:: --verbose

   Provide verbose output during execution.

.. option:: --dry-run

   Show what limits would be created without actually creating them.

.. rubric:: Return codes

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Return code
     - Description
   * - 0
     - Command completed successfully
   * - 1
     - An unexpected error occurred
   * - 2
     - Failed to connect to the database


See Also
========

:doc:`nova-policy(1) <nova-policy>`,
:doc:`nova-status(1) <nova-status>`


Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
