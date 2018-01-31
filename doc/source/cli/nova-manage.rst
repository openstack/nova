===========
nova-manage
===========

-------------------------------------------
Control and manage cloud computer instances
-------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2017-01-15
:Copyright: OpenStack Foundation
:Version: 15.0.0
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-manage <category> <action> [<args>]

Description
===========

`nova-manage` controls cloud computing instances by managing various admin-only
aspects of Nova.

Options
=======

The standard pattern for executing a nova-manage command is::

  nova-manage <category> <command> [<args>]

Run without arguments to see a list of available command categories::

  nova-manage

You can also run with a category argument such as user to see a list of all
commands in that category::

  nova-manage db

These sections describe the available categories and arguments for nova-manage.

Nova Database
~~~~~~~~~~~~~

``nova-manage db version``

    Print the current main database version.

``nova-manage db sync [--version <version>] [--local_cell]``

    Upgrade the main database schema up to the most recent version or
    ``--version`` if specified. By default, this command will also attempt to
    upgrade the schema for the cell0 database if it is mapped (see the
    ``map_cell0`` or ``simple_cell_setup`` commands for more details on mapping
    the cell0 database). If ``--local_cell`` is specified, then only the main
    database in the current cell is upgraded. The local database connection is
    determined by ``[database]/connection`` in the configuration file passed to
    nova-manage.

``nova-manage db archive_deleted_rows [--max_rows <number>] [--verbose] [--until-complete]``

    Move deleted rows from production tables to shadow tables. Specifying
    --verbose will print the results of the archive operation for any tables
    that were changed. Specifying --until-complete will make the command run
    continuously until all deleted rows are archived. Use the --max_rows option,
    which defaults to 1000, as a batch size for each iteration.

``nova-manage db null_instance_uuid_scan [--delete]``

    Lists and optionally deletes database records where instance_uuid is NULL.

``nova-manage db online_data_migrations [--max-count]``

   Perform data migration to update all live data. Return exit code 0 if
   migrations were successful or exit code 1 for partial updates. This command
   should be called after upgrading database schema and nova services on all
   controller nodes. If the command exits with partial updates (exit code 1)
   the command will need to be called again.

   ``--max-count`` controls the maximum number of objects to migrate in a given
   call. If not specified, migration will occur in batches of 50 until fully
   complete.

``nova-manage db ironic_flavor_migration [--all] [--host] [--node] [--resource_class]``

   Perform the ironic flavor migration process against the database
   while services are offline. This is `not recommended` for most
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

Nova API Database
~~~~~~~~~~~~~~~~~

``nova-manage api_db version``

    Print the current cells api database version.

``nova-manage api_db sync``

    Sync the api cells database up to the most recent version. This is the standard way to create the db as well.

.. _man-page-cells-v2:

Nova Cells v2
~~~~~~~~~~~~~

``nova-manage cell_v2 simple_cell_setup [--transport-url <transport_url>]``

    Setup a fresh cells v2 environment; this should not be used if you
    currently have a cells v1 environment. Returns 0 if setup is completed
    (or has already been done), 1 if no hosts are reporting (and cannot be
    mapped), 1 if no transport url is provided for the cell message queue,
    and 2 if run in a cells v1 environment.

``nova-manage cell_v2 map_cell0 [--database_connection <database_connection>]``

    Create a cell mapping to the database connection for the cell0 database.
    If a database_connection is not specified, it will use the one defined by
    ``[database]/connection`` in the configuration file passed to nova-manage.
    The cell0 database is used for instances that have not been scheduled to
    any cell. This generally applies to instances that have encountered an
    error before they have been scheduled. Returns 0 if cell0 is created
    successfully or already setup.

``nova-manage cell_v2 map_instances --cell_uuid <cell_uuid> [--max-count <max_count>]``

    Map instances to the provided cell. Instances in the nova database will
    be queried from oldest to newest and mapped to the provided cell. A
    max_count can be set on the number of instance to map in a single run.
    Repeated runs of the command will start from where the last run finished
    so it is not necessary to increase max-count to finish. Returns 0 if all
    instances have been mapped, and 1 if there are still instances to be
    mapped.

    If ``--max-count`` is not specified, all instances in the cell will be
    mapped in batches of 50. If you have a large number of instances, consider
    specifying a custom value and run the command until it exits with 0.

``nova-manage cell_v2 map_cell_and_hosts [--name <cell_name>] [--transport-url <transport_url>] [--verbose]``

    Create a cell mapping to the database connection and message queue
    transport url, and map hosts to that cell. The database connection
    comes from the ``[database]/connection`` defined in the configuration
    file passed to nova-manage. If a transport_url is not specified, it will
    use the one defined by ``[DEFAULT]/transport_url`` in the configuration
    file. This command is idempotent (can be run multiple times), and the
    verbose option will print out the resulting cell mapping uuid. Returns 0
    on successful completion, and 1 if the transport url is missing.

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

``nova-manage cell_v2 create_cell [--name <cell_name>] [--transport-url <transport_url>] [--database_connection <database_connection>] [--verbose]``

    Create a cell mapping to the database connection and message queue
    transport url. If a database_connection is not specified, it will use the
    one defined by ``[database]/connection`` in the configuration file passed
    to nova-manage. If a transport_url is not specified, it will use the one
    defined by ``[DEFAULT]/transport_url`` in the configuration file.  The
    verbose option will print out the resulting cell mapping uuid.  Returns 0
    if the cell mapping was successfully created, 1 if the transport url or
    database connection was missing, and 2 if a cell is already using that
    transport url and database connection combination.

``nova-manage cell_v2 discover_hosts [--cell_uuid <cell_uuid>] [--verbose] [--strict]``

    Searches cells, or a single cell, and maps found hosts. This command will
    check the database for each cell (or a single one if passed in) and map any
    hosts which are not currently mapped. If a host is already mapped nothing
    will be done. You need to re-run this command each time you add more
    compute hosts to a cell (otherwise the scheduler will never place instances
    there and the API will not list the new hosts). If the strict option is
    provided the command will only be considered successful if an unmapped host
    is discovered (exit code 0). Any other case is considered a failure (exit
    code 1).

``nova-manage cell_v2 list_cells [--verbose]``

    Lists the v2 cells in the deployment. By default only the cell name and
    uuid are shown. Use the --verbose option to see transport url and database
    connection details.

``nova-manage cell_v2 delete_cell [--force] --cell_uuid <cell_uuid>``

    Delete a cell by the given uuid. Returns 0 if the empty cell is
    found and deleted successfully or the cell that has hosts is found and
    the cell and the hosts are deleted successfully with ``--force`` option,
    1 if a cell with that uuid could not be found, 2 if host mappings were
    found for the cell (cell not empty) without ``--force`` option, and 3
    if there are instances mapped to the cell (cell not empty), 4 if there are
    instance mappings to the cell but all instances have been deleted
    in the cell.

``nova-manage cell_v2 list_hosts [--cell_uuid <cell_uuid>]``

    Lists the hosts in one or all v2 cells. By default hosts in all v2 cells
    are listed. Use the --cell_uuid option to list hosts in a specific cell.
    If the cell is not found by uuid, this command will return an exit code
    of 1. Otherwise, the exit code will be 0.

``nova-manage cell_v2 update_cell --cell_uuid <cell_uuid> [--name <cell_name>] [--transport-url <transport_url>] [--database_connection <database_connection>]``

    Updates the properties of a cell by the given uuid. If a
    database_connection is not specified, it will attempt to use the one
    defined by ``[database]/connection`` in the configuration file.  If a
    transport_url is not specified, it will attempt to use the one defined by
    ``[DEFAULT]/transport_url`` in the configuration file. If the cell is not
    found by uuid, this command will return an exit code of 1. If the provided
    transport_url or/and database_connection is/are same as another cell,
    this command will return an exit code of 3. If the properties cannot be set,
    this will return 2. Otherwise, the exit code will be 0.

    .. note::

      Updating the ``transport_url`` or ``database_connection`` fields on a
      running system will NOT result in all nodes immediately using the new
      values.  Use caution when changing these values.

``nova-manage cell_v2 delete_host --cell_uuid <cell_uuid> --host <host>``

    Delete a host by the given host name and the given cell uuid. Returns 0
    if the empty host is found and deleted successfully, 1 if a cell with
    that uuid could not be found, 2 if a host with that name could not be
    found, 3 if a host with that name is not in a cell with that uuid, 4 if
    a host with that name has instances (host not empty).

See Also
========

* `OpenStack Nova <https://docs.openstack.org/nova/latest/>`__

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
