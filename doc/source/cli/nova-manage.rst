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

These sections describe the available categories and arguments for
:program:`nova-manage`.

Options
=======

These options apply to all commands and may be given in any order, before or
after commands. Individual commands may provide additional options. Options
without an argument can be combined after a single dash.

.. option:: -h, --help

    Show a help message and exit

.. option:: --config-dir DIR

    Path to a config directory to pull ``*.conf`` files from. This file set is
    sorted, so as to provide a predictable parse order if individual options
    are over-ridden. The set is parsed after the file(s) specified via previous
    :option:`--config-file`, arguments hence over-ridden options in the
    directory take precedence.  This option must be set from the command-line.

.. option:: --config-file PATH

    Path to a config file to use. Multiple config files can be specified, with
    values in later files taking precedence. Defaults to None. This option must
    be set from the command-line.

.. option:: --debug, -d

    If set to true, the logging level will be set to DEBUG instead of the
    default INFO level.

.. option:: --log-config-append PATH, --log-config PATH, --log_config PATH

    The name of a logging configuration file. This file is appended to any
    existing logging configuration files.  For details about logging
    configuration files, see the Python logging module documentation. Note that
    when logging configuration files are used then all logging configuration is
    set in the configuration file and other logging configuration options are
    ignored (for example, :option:`--log-date-format`).

.. option:: --log-date-format DATE_FORMAT

    Defines the format string for ``%(asctime)s`` in log records. Default:
    None. This option is ignored if :option:`--log-config-append` is set.

.. option:: --log-dir LOG_DIR, --logdir LOG_DIR

    (Optional) The base directory used for relative log_file paths. This option
    is ignored if :option:`--log-config-append` is set.

.. option:: --log-file PATH, --logfile PATH

    (Optional) Name of log file to send logging output to.  If no default is
    set, logging will go to stderr as defined by use_stderr. This option is
    ignored if :option:`--log-config-append` is set.

.. option:: --nodebug

    The inverse of :option:`--debug`.

.. option:: --nopost-mortem

    The inverse of :option:`--post-mortem`.

.. option:: --nouse-journal

    The inverse of :option:`--use-journal`.

.. option:: --nouse-json

    The inverse of :option:`--use-json`.

.. option:: --nouse-syslog

    The inverse of :option:`--use-syslog`.

.. option:: --nowatch-log-file

    The inverse of :option:`--watch-log-file`.

.. option:: --post-mortem

    Allow post-mortem debugging

.. option:: --syslog-log-facility SYSLOG_LOG_FACILITY

    Syslog facility to receive log lines. This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --use-journal

    Enable journald for logging. If running in a systemd environment you may
    wish to enable journal support.  Doing so will use the journal native
    protocol which includes structured metadata in addition to log
    messages. This option is ignored if :option:`--log-config-append` is
    set.

.. option:: --use-json

    Use JSON formatting for logging. This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --use-syslog

    Use syslog for logging. Existing syslog format is DEPRECATED and will be
    changed later to honor RFC5424.  This option is ignored if
    :option:`--log-config-append` is set.

.. option:: --version

    Show program's version number and exit

.. option:: --watch-log-file

    Uses logging handler designed to watch file system.  When log file is moved
    or removed this handler will open a new log file with specified path
    instantaneously. It makes sense only if :option:`--log-file` option is
    specified and Linux platform is used. This option is ignored if
    :option:`--log-config-append` is set.

Commands
========

Nova Database
~~~~~~~~~~~~~

``nova-manage db version``
    Print the current main database version.

``nova-manage db sync [--local_cell] [VERSION]``
    Upgrade the main database schema up to the most recent version or
    ``VERSION`` if specified. By default, this command will also attempt to
    upgrade the schema for the cell0 database if it is mapped (see the
    ``map_cell0`` or ``simple_cell_setup`` commands for more details on mapping
    the cell0 database). If ``--local_cell`` is specified, then only the main
    database in the current cell is upgraded. The local database connection is
    determined by :oslo.config:option:`database.connection` in the
    configuration file, passed to nova-manage using the ``--config-file``
    option(s). This command should be run after ``nova-manage api_db sync``.

    Returns exit code 0 if the database schema was synced successfully, or 1 if
    cell0 cannot be accessed.

``nova-manage db archive_deleted_rows [--max_rows <number>] [--verbose] [--until-complete] [--before <date>] [--purge] [--all-cells]``
    Move deleted rows from production tables to shadow tables. Note that the
    corresponding rows in the ``instance_mappings``, ``request_specs`` and
    ``instance_group_member`` tables of the API database are purged when
    instance records are archived and thus,
    :oslo.config:option:`api_database.connection` is required in the config
    file. Specifying ``--verbose`` will print the results of the archive
    operation for any tables that were changed. Specifying ``--until-complete``
    will make the command run continuously until all deleted rows are archived.
    Use the ``--max_rows`` option, which defaults to 1000, as a batch size for
    each iteration (note that the purged API database table records are not
    included in this batch size). Specifying ``--before`` will archive only
    instances that were deleted before the date_ provided, and records in other
    tables related to those instances. Specifying ``--purge`` will cause a
    *full* DB purge to be completed after archival. If a date range is desired
    for the purge, then run ``nova-manage db purge --before <date>`` manually
    after archiving is complete. Specifying ``--all-cells`` will
    cause the process to run against all cell databases.

    **Return Codes**

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
         - Invalid value for ``--max_rows``.
       * - 3
         - No connection to the API database could be established using
           :oslo.config:option:`api_database.connection`.
       * - 4
         - Invalid value for ``--before``.
       * - 255
         - An unexpected error occurred.

    If automating, this should be run continuously while the result is 1,
    stopping at 0, or use the ``--until-complete`` option.

``nova-manage db purge [--all] [--before <date>] [--verbose] [--all-cells]``
    Delete rows from shadow tables. Specifying ``--all`` will delete all data from
    all shadow tables. Specifying ``--before`` will delete data from all shadow tables
    that is older than the date_ provided. Specifying ``--verbose`` will
    cause information to be printed about purged records. Specifying
    ``--all-cells`` will cause the purge to be applied against all cell databases.
    For ``--all-cells`` to work, the api database connection information must
    be configured. Returns exit code 0 if rows were deleted, 1 if required
    arguments are not provided, 2 if an invalid date is provided, 3 if no
    data was deleted, 4 if the list of cells cannot be obtained.

``nova-manage db null_instance_uuid_scan [--delete]``
    Lists and optionally deletes database records where instance_uuid is NULL.

``nova-manage db online_data_migrations [--max-count]``
   Perform data migration to update all live data.

   ``--max-count`` controls the maximum number of objects to migrate in a given
   call. If not specified, migration will occur in batches of 50 until fully
   complete.

   Returns exit code 0 if no (further) updates are possible, 1 if the ``--max-count``
   option was used and some updates were completed successfully (even if others generated
   errors), 2 if some updates generated errors and no other migrations were able to take
   effect in the last batch attempted, or 127 if invalid input is provided (e.g.
   non-numeric max-count).

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
   which did require a data migration. Since ``--max-count`` defaults to 50
   and only two records were migrated with no more candidates remaining, the
   command completed successfully with exit code 0.

``nova-manage db ironic_flavor_migration [--all] [--host] [--node] [--resource_class]``
   Perform the ironic flavor migration process against the database
   while services are offline. This is *not recommended* for most
   people. The ironic compute driver will do this online and as
   necessary if run normally. This routine is provided only for
   advanced users that may be skipping the 16.0.0 Pike release, never
   able to run services normally at the Pike level. Since this utility
   is for use when all services (including ironic) are down, you must
   pass the resource class set on your node(s) with the
   ``--resource_class`` parameter.

   To migrate a specific host and node, provide the hostname and node uuid with
   ``--host $hostname --node $uuid``. To migrate all instances on nodes managed
   by a single host, provide only ``--host``. To iterate over all nodes in the
   system in a single pass, use ``--all``. Note that this process is not lightweight,
   so it should not be run frequently without cause, although it is not harmful
   to do so. If you have multiple cellsv2 cells, you should run this once per cell
   with the corresponding cell config for each (i.e. this does not iterate cells
   automatically).

   Note that this is not recommended unless you need to run this
   specific data migration offline, and it should be used with care as
   the work done is non-trivial. Running smaller and more targeted batches (such as
   specific nodes) is recommended.

.. _date:

``--before <date>``
   The date argument accepted by the ``--before`` option can be in any
   of several formats, including ``YYYY-MM-DD [HH:mm[:ss]]`` and the default
   format produced by the ``date`` command, e.g. ``Fri May 24 09:20:11 CDT 2019``.
   Date strings containing spaces must be quoted appropriately. Some examples::

     # Purge shadow table rows older than a specific date
     nova-manage db purge --before 2015-10-21
     # or
     nova-manage db purge --before "Oct 21 2015"
     # Times are also accepted
     nova-manage db purge --before "2015-10-21 12:00"

   Note that relative dates (such as ``yesterday``) are not supported natively.
   The ``date`` command can be helpful here::

     # Archive deleted rows more than one month old
     nova-manage db archive_deleted_rows --before "$(date -d 'now - 1 month')"

Nova API Database
~~~~~~~~~~~~~~~~~

``nova-manage api_db version``
    Print the current API database version.

``nova-manage api_db sync [VERSION]``
    Upgrade the API database schema up to the most recent version or
    ``VERSION`` if specified. This command does not create the API
    database, it runs schema migration scripts. The API database connection is
    determined by :oslo.config:option:`api_database.connection` in the
    configuration file passed to nova-manage.

    In the 18.0.0 Rocky or 19.0.0 Stein release, this command will also upgrade
    the optional placement database if ``[placement_database]/connection`` is
    configured.

    Returns exit code 0 if the database schema was synced successfully. This
    command should be run before ``nova-manage db sync``.

.. _man-page-cells-v2:

Nova Cells v2
~~~~~~~~~~~~~

``nova-manage cell_v2 simple_cell_setup [--transport-url <transport_url>]``
    Setup a fresh cells v2 environment. If a ``transport_url`` is not
    specified, it will use the one defined by :oslo.config:option:`transport_url`
    in the configuration file. Returns 0 if setup is completed
    (or has already been done), 1 if no hosts are reporting (and cannot be
    mapped) and 1 if the transport url is missing or invalid.

``nova-manage cell_v2 map_cell0 [--database_connection <database_connection>]``
    Create a cell mapping to the database connection for the cell0 database.
    If a database_connection is not specified, it will use the one defined by
    :oslo.config:option:`database.connection` in the configuration file passed
    to nova-manage. The cell0 database is used for instances that have not been
    scheduled to any cell. This generally applies to instances that have
    encountered an error before they have been scheduled. Returns 0 if cell0 is
    created successfully or already setup.

``nova-manage cell_v2 map_instances --cell_uuid <cell_uuid> [--max-count <max_count>] [--reset]``
    Map instances to the provided cell. Instances in the nova database will
    be queried from oldest to newest and mapped to the provided cell. A
    ``--max-count`` can be set on the number of instance to map in a single run.
    Repeated runs of the command will start from where the last run finished
    so it is not necessary to increase ``--max-count`` to finish. A ``--reset``
    option can be passed which will reset the marker, thus making the command
    start from the beginning as opposed to the default behavior of starting from
    where the last run finished.

    If ``--max-count`` is not specified, all instances in the cell will be
    mapped in batches of 50. If you have a large number of instances, consider
    specifying a custom value and run the command until it exits with 0.

    **Return Codes**

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
         - Invalid value for ``--max-count``.
       * - 255
         - An unexpected error occurred.

``nova-manage cell_v2 map_cell_and_hosts [--name <cell_name>] [--transport-url <transport_url>] [--verbose]``
    Create a cell mapping to the database connection and message queue
    transport url, and map hosts to that cell. The database connection
    comes from the :oslo.config:option:`database.connection` defined in the
    configuration file passed to nova-manage. If a transport_url is not
    specified, it will use the one defined by
    :oslo.config:option:`transport_url` in the configuration file. This command
    is idempotent (can be run multiple times), and the verbose option will
    print out the resulting cell mapping uuid. Returns 0 on successful
    completion, and 1 if the transport url is missing or invalid.

``nova-manage cell_v2 verify_instance --uuid <instance_uuid> [--quiet]``
    Verify instance mapping to a cell. This command is useful to determine if
    the cells v2 environment is properly setup, specifically in terms of the
    cell, host, and instance mapping records required. Returns 0 when the
    instance is successfully mapped to a cell, 1 if the instance is not
    mapped to a cell (see the ``map_instances`` command), 2 if the cell
    mapping is missing (see the ``map_cell_and_hosts`` command if you are
    upgrading from a cells v1 environment, and the ``simple_cell_setup`` if
    you are upgrading from a non-cells v1 environment), 3 if it is a deleted
    instance which has instance mapping, and 4 if it is an archived instance
    which still has an instance mapping.

``nova-manage cell_v2 create_cell [--name <cell_name>] [--transport-url <transport_url>] [--database_connection <database_connection>] [--verbose] [--disabled]``
    Create a cell mapping to the database connection and message queue
    transport url. If a database_connection is not specified, it will use the
    one defined by :oslo.config:option:`database.connection` in the
    configuration file passed to nova-manage. If a transport_url is not
    specified, it will use the one defined by
    :oslo.config:option:`transport_url` in the configuration file. The verbose
    option will print out the resulting cell mapping uuid. All the cells
    created are by default enabled. However passing the ``--disabled`` option
    can create a pre-disabled cell, meaning no scheduling will happen to this
    cell. The meaning of the various exit codes returned by this command are
    explained below:

    * Returns 0 if the cell mapping was successfully created.
    * Returns 1 if the transport url or database connection was missing
      or invalid.
    * Returns 2 if another cell is already using that transport url and/or
      database connection combination.

``nova-manage cell_v2 discover_hosts [--cell_uuid <cell_uuid>] [--verbose] [--strict] [--by-service]``
    Searches cells, or a single cell, and maps found hosts. This command will
    check the database for each cell (or a single one if passed in) and map any
    hosts which are not currently mapped. If a host is already mapped, nothing
    will be done. You need to re-run this command each time you add a batch of
    compute hosts to a cell (otherwise the scheduler will never place instances
    there and the API will not list the new hosts). If ``--strict`` is specified,
    the command will only return 0 if an unmapped host was discovered and
    mapped successfully. If ``--by-service`` is specified, this command will look
    in the appropriate cell(s) for any nova-compute services and ensure there
    are host mappings for them. This is less efficient and is only necessary
    when using compute drivers that may manage zero or more actual compute
    nodes at any given time (currently only ironic).

    This command should be run once after all compute hosts have been deployed
    and should not be run in parallel. When run in parallel, the commands will
    collide with each other trying to map the same hosts in the database at the
    same time.

    The meaning of the various exit codes returned by this command are
    explained below:

    * Returns 0 if hosts were successfully mapped or no hosts needed to be
      mapped. If ``--strict`` is specified, returns 0 only if an unmapped host was
      discovered and mapped.
    * Returns 1 if ``--strict`` is specified and no unmapped hosts were found.
      Also returns 1 if an exception was raised while running.
    * Returns 2 if the command aborted because of a duplicate host mapping
      found. This means the command collided with another running
      discover_hosts command or scheduler periodic task and is safe to retry.

``nova-manage cell_v2 list_cells [--verbose]``
    By default the cell name, uuid, disabled state, masked transport URL and
    database connection details are shown. Use the ``--verbose`` option to see
    transport URL and database connection with their sensitive details.

``nova-manage cell_v2 delete_cell [--force] --cell_uuid <cell_uuid>``
    Delete a cell by the given uuid. Returns 0 if the empty cell is found and
    deleted successfully or the cell that has hosts is found and the cell, hosts
    and the instance_mappings are deleted successfully with ``--force`` option
    (this happens if there are no living instances), 1 if a cell with that uuid
    could not be found, 2 if host mappings were found for the cell (cell not empty)
    without ``--force`` option, 3 if there are instances mapped to the cell
    (cell not empty) irrespective of the ``--force`` option, and 4 if there are
    instance mappings to the cell but all instances have been deleted in the cell,
    again without the ``--force`` option.

``nova-manage cell_v2 list_hosts [--cell_uuid <cell_uuid>]``
    Lists the hosts in one or all v2 cells. By default hosts in all v2 cells
    are listed. Use the ``--cell_uuid`` option to list hosts in a specific cell.
    If the cell is not found by uuid, this command will return an exit code
    of 1. Otherwise, the exit code will be 0.

``nova-manage cell_v2 update_cell --cell_uuid <cell_uuid> [--name <cell_name>] [--transport-url <transport_url>] [--database_connection <database_connection>] [--disable] [--enable]``
    Updates the properties of a cell by the given uuid. If a
    database_connection is not specified, it will attempt to use the one
    defined by :oslo.config:option:`database.connection` in the configuration
    file. If a transport_url is not specified, it will attempt to use the one
    defined by :oslo.config:option:`transport_url` in the configuration file.
    The meaning of the various exit codes returned by this command are
    explained below:

    * If successful, it will return 0.
    * If the cell is not found by the provided uuid, it will return 1.
    * If the properties cannot be set, it will return 2.
    * If the provided transport_url or/and database_connection is/are same as
      another cell, it will return 3.
    * If an attempt is made to disable and enable a cell at the same time, it
      will return 4.
    * If an attempt is made to disable or enable cell0 it will return 5.

    .. note::

      Updating the ``transport_url`` or ``database_connection`` fields on a
      running system will NOT result in all nodes immediately using the new
      values.  Use caution when changing these values.

      The scheduler will not notice that a cell has been enabled/disabled until
      it is restarted or sent the SIGHUP signal.

``nova-manage cell_v2 delete_host --cell_uuid <cell_uuid> --host <host>``
    Delete a host by the given host name and the given cell uuid. Returns 0
    if the empty host is found and deleted successfully, 1 if a cell with
    that uuid could not be found, 2 if a host with that name could not be
    found, 3 if a host with that name is not in a cell with that uuid, 4 if
    a host with that name has instances (host not empty).

    .. note::

      The scheduler caches host-to-cell mapping information so when deleting
      a host the scheduler may need to be restarted or sent the SIGHUP signal.

Placement
~~~~~~~~~

.. _heal_allocations_cli:

``nova-manage placement heal_allocations [--max-count <max_count>] [--verbose] [--skip-port-allocations] [--dry-run] [--instance <instance_uuid>] [--cell <cell_uuid] [--force]``
    Iterates over non-cell0 cells looking for instances which do not have
    allocations in the Placement service and which are not undergoing a task
    state transition. For each instance found, allocations are created against
    the compute node resource provider for that instance based on the flavor
    associated with the instance.

    Also if the instance has any port attached that has resource request
    (e.g. :neutron-doc:`Quality of Service (QoS): Guaranteed Bandwidth
    <admin/config-qos-min-bw.html>`) but the corresponding
    allocation is not found then the allocation is created against the
    network device resource providers according to the resource request of
    that port. It is possible that the missing allocation cannot be created
    either due to not having enough resource inventory on the host the instance
    resides on or because more than one resource provider could fulfill the
    request. In this case the instance needs to be manually deleted or the
    port needs to be detached.  When nova `supports migrating instances
    with guaranteed bandwidth ports`_, migration will heal missing allocations
    for these instances.

    Before the allocations for the ports are persisted in placement nova-manage
    tries to update each port in neutron to refer to the resource provider UUID
    which provides the requested resources. If any of the port updates fail in
    neutron or the allocation update fails in placement the command tries to
    roll back the partial updates to the ports. If the roll back fails
    then the process stops with exit code ``7`` and the admin needs to do the
    rollback in neutron manually according to the description in the exit code
    section.

    .. _supports migrating instances with guaranteed bandwidth ports: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/support-move-ops-with-qos-ports.html

    There is also a special case handled for instances that *do* have
    allocations created before Placement API microversion 1.8 where project_id
    and user_id values were required. For those types of allocations, the
    project_id and user_id are updated using the values from the instance.

    Specify ``--max-count`` to control the maximum number of instances to
    process. If not specified, all instances in each cell will be mapped in
    batches of 50. If you have a large number of instances, consider
    specifying a custom value and run the command until it exits with 0 or 4.

    Specify ``--verbose`` to get detailed progress output during execution.

    Specify ``--dry-run`` to print output but not commit any changes. The
    return code should be 4. *(Since 20.0.0 Train)*

    Specify ``--instance`` to process a specific instance given its UUID. If
    specified the ``--max-count`` option has no effect.
    *(Since 20.0.0 Train)*

    Specify ``--skip-port-allocations`` to skip the healing of the resource
    allocations of bound ports, e.g. healing bandwidth resource allocation for
    ports having minimum QoS policy rules attached. If your deployment does
    not use such a feature then the performance impact of querying neutron
    ports for each instance can be avoided with this flag.
    *(Since 20.0.0 Train)*

    Specify ``--cell`` to  process heal allocations within a specific cell.
    This is mutually exclusive with the ``--instance`` option.

    Specify ``--force`` to forcefully heal single instance allocation. This
    option needs to be passed with ``--instance``.

    This command requires that the
    :oslo.config:option:`api_database.connection` and
    :oslo.config:group:`placement` configuration options are set. Placement API
    >= 1.28 is required.

    **Return Codes**

    .. list-table::
       :widths: 20 80
       :header-rows: 1

       * - Return code
         - Description
       * - 0
         - Command completed successfully and allocations were created.
       * - 1
         - ``--max-count`` was reached and there are more instances to process.
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

``nova-manage placement sync_aggregates [--verbose]``
    Mirrors compute host aggregates to resource provider aggregates
    in the Placement service. Requires the :oslo.config:group:`api_database`
    and :oslo.config:group:`placement` sections of the nova configuration file
    to be populated.

    Specify ``--verbose`` to get detailed progress output during execution.

    .. note:: Depending on the size of your deployment and the number of
        compute hosts in aggregates, this command could cause a non-negligible
        amount of traffic to the placement service and therefore is
        recommended to be run during maintenance windows.

    .. versionadded:: Rocky

    **Return Codes**

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

``nova-manage placement audit [--verbose] [--delete] [--resource_provider <uuid>]``
    Iterates over all the Resource Providers (or just one if you provide the
    UUID) and then verifies if the compute allocations are either related to
    an existing instance or a migration UUID.
    If not, it will tell which allocations are orphaned.

    You can also ask to delete all the orphaned allocations by specifying
    ``-delete``.

    Specify ``--verbose`` to get detailed progress output during execution.

    This command requires that the
    :oslo.config:option:`api_database.connection` and
    :oslo.config:group:`placement` configuration options are set. Placement API
    >= 1.14 is required.

    **Return Codes**

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


See Also
========

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
