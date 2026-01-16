Nova service concurrency
========================

For a long time nova services relied almost exclusively on the Eventlet library
for processing multiple API requests, RPC requests and other tasks that needed
concurrency. Since Eventlet is not expected to support the next major cPython
version the OpenStack TC set a `goal`__ to replace Eventlet and therefore Nova
has started transitioning its concurrency model to native threads. During this
transition Nova maintains the Eventlet based concurrency mode while building
up support for the native threading mode.

.. __: https://governance.openstack.org/tc/goals/selected/remove-eventlet.html

.. note::

   The native threading mode is experimental. Do not use it in production
   without first testing it in pre-production. If you do so please let us now
   how it went on the mailing list openstack-discuss@lists.openstack.org.


Selecting concurrency mode for a service
----------------------------------------

Since nova 33.0.0 (2026.1 Gazpacho) the nova-scheduler, nova-api, and
nova-metadata are using native threading by default. The rest of the
services are using eventlet by default in this release. The concurrency mode
can be configured per service via setting the environment variable
``OS_NOVA_DISABLE_EVENTLET_PATCHING``. Setting that variable to ``true``
requests the native threading mode while setting it to ``false`` requests the
eventlet mode. If the variable is not set the above default is applied.

.. note::

   Since nova 32.0.0 (2025.2 Flamingo) the nova-scheduler, nova-metadata, and
   nova-api can be switched to native threading mode.

   Since nova 33.0.0 (2026.1 Gazpacho) also the nova-conductor can be switched
   to native threading mode.

   Since nova 33.0.0 (2026.1. Gazpacho) the nova-scheduler, nova-metadata, and
   nova-api using native threading mode by default but still can be switched
   back to eventlet if needed.


Tunables for the native threading mode
--------------------------------------
As native threads are more expensive resources than greenthreads Nova provides
a set of configuration options to allow fine tuning the deployment based on
load and resource constraints. The default values are selected to support a
basic, small deployment without consuming substantially more memory resources,
than the legacy Eventlet mode. Increasing the size of the below thread pools
means that the given service will consume more memory but will also allow more
tasks to be executed concurrently.

* :oslo.config:option:`cell_worker_thread_pool_size`: Used to execute tasks
  across all the cells within the deployment.

  E.g. To generate the result of the ``openstack server list`` CLI command, the
  nova-api service will use one native thread for each cell to load the nova
  instances from the related cell database.

  So if the deployment has many cells then the size of this pool probably needs
  to be increased.

  This option is only relevant for nova-api, nova-metadata, nova-scheduler, and
  nova-conductor as these are the services doing cross cell operations.

* :oslo.config:option:`executor_thread_pool_size`: Used to handle incoming RPC
  requests. Services with many more inbound requests will need larger pools.
  For example, a single conductor serves requests from many computes as well
  as the scheduler. A compute node only serves requests from the API for
  lifecycle operations and other computes during migrations.

  This option is only relevant for nova-scheduler, nova-conductor, and
  nova-compute as these are the services acting as RPC servers.

* :oslo.config:option:`default_thread_pool_size`: Used by various concurrent
  tasks in the service that are not categorized into the above pools.

  This option is relevant to every nova service using ``nova.utils.spawn()``.

* :oslo.config:option:`sync_power_state_pool_size`: Used by the
  nova-compute service to sync the power state of each instance on the host
  between the hypervisor and the DB. Since nova 33.0.0 (2026.1 Gazpacho) the
  default value of this option is changed from 1000 to 5 to have a sane default
  in native threading mode. Increasing this value in native threading mode
  increases the nova-compute memory consumption on a host that has many
  instances.

* :oslo.config:option:`max_concurrent_live_migrations`: Used by the
  nova-compute service to limit the number of outgoing concurrent live
  migrations from the host. It is implemented via a thread pool. So increasing
  the the number of concurrent live migrations will increase the nova-compute
  service memory consumption in native threading mode. It is almost always
  a bad idea to use change this config option from its default value, 1. If
  more performant live migration is needed then enable
  :oslo.config:option:`libvirt.live_migration_parallel_connections` instead.

Seeing the usage of the pools
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When new work is submitted to any of these pools in both concurrency modes
Nova logs the statistics of the pool (work executed, threads available,
work queued, etc).
This can be useful when fine tuning of the pool size is needed.
The parameter :oslo.config:option:`thread_pool_statistic_period` defines how
frequently such logging happens from a specific pool in seconds. A value of
60 seconds means that stats will be logged from a pool maximum once every
60 seconds. The value 0 means that logging happens every time work is submitted
to the pool. The default value is -1 meaning that the stats logging is
disabled.

Preventing hanging threads
~~~~~~~~~~~~~~~~~~~~~~~~~~

Threads from a pool are not cancellable once they are executing a task,
therefore it is important to ensure external dependencies cannot hold up a
task execution indefinitely as that will lead to having fewer threads in the
pool available for incoming work and therefore reduced overall capacity.

Nova's RPC interface already uses proper timeout handling to avoid hanging
threads. But adding timeout handling to the Nova's database interface is
database server and database client library dependent.

For mysql-server the `max_execution_time`__ configuration option can be used
to limit the execution time of a database query on the server side. Similar
options exist for other database servers.

.. __: https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html#sysvar_max_execution_time

For the pymysql database client a client side timeout can be implemented by
adding the `read_timeout`__ connection parameter to the connection string.

.. __: https://pymysql.readthedocs.io/en/latest/modules/connections.html#module-pymysql.connections

We recommend using both in deployments where Nova services are running in
native threading mode.

Upgrading to nova 33.0.0 (2026.1. Gazpacho) or newer
----------------------------------------------------

In nova 33.0.0 (2026.1. Gazpacho) the default concurrency mode of
nova-scheduler, nova-api, and nova-metadata service are switched to native
threading. We recommend to decouple the upgrade from the concurrency mode
change to reduce the risk of issues. To do that either test and tune the native
threading mode of these services already in 2025.2 (Flamingo) or ensure that
your service configuration is explicitly using the eventlet mode before you
upgrade and only change to threading mode after the upgrade was successful.
