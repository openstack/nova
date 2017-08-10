==========
Cells (v1)
==========

.. warning::

   Configuring and implementing Cells v1 is not recommended for new deployments
   of the Compute service (nova). Cells v2 replaces cells v1, and v2 is
   required to install or upgrade the Compute service to the 15.0.0 Ocata
   release. More information on cells v2 can be found in :doc:`/user/cells`.

`Cells` functionality enables you to scale an OpenStack Compute cloud in a more
distributed fashion without having to use complicated technologies like
database and message queue clustering.  It supports very large deployments.

When this functionality is enabled, the hosts in an OpenStack Compute cloud are
partitioned into groups called cells. Cells are configured as a tree. The
top-level cell should have a host that runs a ``nova-api`` service, but no
``nova-compute`` services.  Each child cell should run all of the typical
``nova-*`` services in a regular Compute cloud except for ``nova-api``. You can
think of cells as a normal Compute deployment in that each cell has its own
database server and message queue broker.

The ``nova-cells`` service handles communication between cells and selects
cells for new instances. This service is required for every cell. Communication
between cells is pluggable, and currently the only option is communication
through RPC.

Cells scheduling is separate from host scheduling.  ``nova-cells`` first picks
a cell. Once a cell is selected and the new build request reaches its
``nova-cells`` service, it is sent over to the host scheduler in that cell and
the build proceeds as it would have without cells.

Cell configuration options
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. todo:: This is duplication. We should be able to use the
     oslo.config.sphinxext module to generate this for us

Cells are disabled by default. All cell-related configuration options appear in
the ``[cells]`` section in ``nova.conf``.  The following cell-related options
are currently supported:

``enable``
  Set to ``True`` to turn on cell functionality. Default is ``false``.

``name``
  Name of the current cell. Must be unique for each cell.

``capabilities``
  List of arbitrary ``key=value`` pairs defining capabilities of the current
  cell. Values include ``hypervisor=xenserver;kvm,os=linux;windows``.

``call_timeout``
  How long in seconds to wait for replies from calls between cells.

``scheduler_filter_classes``
  Filter classes that the cells scheduler should use.  By default, uses
  ``nova.cells.filters.all_filters`` to map to all cells filters included with
  Compute.

``scheduler_weight_classes``
  Weight classes that the scheduler for cells uses. By default, uses
  ``nova.cells.weights.all_weighers`` to map to all cells weight algorithms
  included with Compute.

``ram_weight_multiplier``
  Multiplier used to weight RAM. Negative numbers indicate that Compute should
  stack VMs on one host instead of spreading out new VMs to more hosts in the
  cell. The default value is 10.0.

Configure the API (top-level) cell
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The cell type must be changed in the API cell so that requests can be proxied
through ``nova-cells`` down to the correct cell properly.  Edit the
``nova.conf`` file in the API cell, and specify ``api`` in the ``cell_type``
key:

.. code-block:: ini

   [DEFAULT]
   compute_api_class=nova.compute.cells_api.ComputeCellsAPI
   # ...

   [cells]
   cell_type= api

Configure the child cells
~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the ``nova.conf`` file in the child cells, and specify ``compute`` in the
``cell_type`` key:

.. code-block:: ini

   [DEFAULT]
   # Disable quota checking in child cells. Let API cell do it exclusively.
   quota_driver=nova.quota.NoopQuotaDriver

   [cells]
   cell_type = compute

Configure the database in each cell
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before bringing the services online, the database in each cell needs to be
configured with information about related cells.  In particular, the API cell
needs to know about its immediate children, and the child cells must know about
their immediate agents.  The information needed is the ``RabbitMQ`` server
credentials for the particular cell.

Use the :command:`nova-manage cell create` command to add this information to
the database in each cell:

.. code-block:: console

   # nova-manage cell create -h
   usage: nova-manage cell create [-h] [--name <name>]
                                  [--cell_type <parent|api|child|compute>]
                                  [--username <username>] [--password <password>]
                                  [--broker_hosts <broker_hosts>]
                                  [--hostname <hostname>] [--port <number>]
                                  [--virtual_host <virtual_host>]
                                  [--woffset <float>] [--wscale <float>]

   optional arguments:
     -h, --help            show this help message and exit
     --name <name>         Name for the new cell
     --cell_type <parent|api|child|compute>
                           Whether the cell is parent/api or child/compute
     --username <username>
                           Username for the message broker in this cell
     --password <password>
                           Password for the message broker in this cell
     --broker_hosts <broker_hosts>
                           Comma separated list of message brokers in this cell.
                           Each Broker is specified as hostname:port with both
                           mandatory. This option overrides the --hostname and
                           --port options (if provided).
     --hostname <hostname>
                           Address of the message broker in this cell
     --port <number>       Port number of the message broker in this cell
     --virtual_host <virtual_host>
                           The virtual host of the message broker in this cell
     --woffset <float>
     --wscale <float>

As an example, assume an API cell named ``api`` and a child cell named
``cell1``.

Within the ``api`` cell, specify the following ``RabbitMQ`` server information:

.. code-block:: ini

   rabbit_host=10.0.0.10
   rabbit_port=5672
   rabbit_username=api_user
   rabbit_password=api_passwd
   rabbit_virtual_host=api_vhost

Within the ``cell1`` child cell, specify the following ``RabbitMQ`` server
information:

.. code-block:: ini

   rabbit_host=10.0.1.10
   rabbit_port=5673
   rabbit_username=cell1_user
   rabbit_password=cell1_passwd
   rabbit_virtual_host=cell1_vhost

You can run this in the API cell as root:

.. code-block:: console

   # nova-manage cell create --name cell1 --cell_type child \
     --username cell1_user --password cell1_passwd --hostname 10.0.1.10 \
     --port 5673 --virtual_host cell1_vhost --woffset 1.0 --wscale 1.0

Repeat the previous steps for all child cells.

In the child cell, run the following, as root:

.. code-block:: console

   # nova-manage cell create --name api --cell_type parent \
     --username api_user --password api_passwd --hostname 10.0.0.10 \
     --port 5672 --virtual_host api_vhost --woffset 1.0 --wscale 1.0

To customize the Compute cells, use the configuration option settings
documented above.

Cell scheduling configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To determine the best cell to use to launch a new instance, Compute uses a set
of filters and weights defined in the ``/etc/nova/nova.conf`` file. The
following options are available to prioritize cells for scheduling:

``scheduler_filter_classes``
  List of filter classes. By default ``nova.cells.filters.all_filters``
  is specified, which maps to all cells filters included with Compute
  (see the section called :ref:`Filters <compute-scheduler-filters>`).

``scheduler_weight_classes``
  List of weight classes. By default ``nova.cells.weights.all_weighers`` is
  specified, which maps to all cell weight algorithms included with Compute.
  The following modules are available:

  ``mute_child``
    Downgrades the likelihood of child cells being chosen for scheduling
    requests, which haven't sent capacity or capability updates in a while.
    Options include ``mute_weight_multiplier`` (multiplier for mute children;
    value should be negative).

  ``ram_by_instance_type``
    Select cells with the most RAM capacity for the instance type being
    requested. Because higher weights win, Compute returns the number of
    available units for the instance type requested. The
    ``ram_weight_multiplier`` option defaults to 10.0 that adds to the weight
    by a factor of 10.

    Use a negative number to stack VMs on one host instead of spreading
    out new VMs to more hosts in the cell.

  ``weight_offset``
    Allows modifying the database to weight a particular cell. You can use this
    when you want to disable a cell (for example, '0'), or to set a default
    cell by making its ``weight_offset`` very high (for example,
    ``999999999999999``).  The highest weight will be the first cell to be
    scheduled for launching an instance.

Additionally, the following options are available for the cell scheduler:

``scheduler_retries``
  Specifies how many times the scheduler tries to launch a new instance when no
  cells are available (default=10).

``scheduler_retry_delay``
  Specifies the delay (in seconds) between retries (default=2).

As an admin user, you can also add a filter that directs builds to a particular
cell. The ``policy.json`` file must have a line with
``"cells_scheduler_filter:TargetCellFilter" : "is_admin:True"`` to let an admin
user specify a scheduler hint to direct a build to a particular cell.

Optional cell configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cells store all inter-cell communication data, including user names and
passwords, in the database. Because the cells data is not updated very
frequently, use the ``[cells]cells_config`` option to specify a JSON file to
store cells data. With this configuration, the database is no longer consulted
when reloading the cells data.  The file must have columns present in the Cell
model (excluding common database fields and the ``id`` column). You must
specify the queue connection information through a ``transport_url`` field,
instead of ``username``, ``password``, and so on.

The ``transport_url`` has the following form::

   rabbit://USERNAME:PASSWORD@HOSTNAME:PORT/VIRTUAL_HOST

The scheme can only be ``rabbit``.

The following sample shows this optional configuration:

.. code-block:: json

   {
       "parent": {
           "name": "parent",
           "api_url": "http://api.example.com:8774",
           "transport_url": "rabbit://rabbit.example.com",
           "weight_offset": 0.0,
           "weight_scale": 1.0,
           "is_parent": true
       },
       "cell1": {
           "name": "cell1",
           "api_url": "http://api.example.com:8774",
           "transport_url": "rabbit://rabbit1.example.com",
           "weight_offset": 0.0,
           "weight_scale": 1.0,
           "is_parent": false
       },
       "cell2": {
           "name": "cell2",
           "api_url": "http://api.example.com:8774",
           "transport_url": "rabbit://rabbit2.example.com",
           "weight_offset": 0.0,
           "weight_scale": 1.0,
           "is_parent": false
       }
   }
