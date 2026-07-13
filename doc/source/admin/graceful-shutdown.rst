=================
Graceful Shutdown
=================

Nova services have experimental graceful shutdown support on ``SIGTERM``. When
a service worker implementing an RPC server receives ``SIGTERM``, that worker
stops accepting new RPC requests and waits for in-progress tasks to reach a
safe termination point before exiting. This reduces the risk of leaving
instances or migrations of instances in an unwanted or unrecoverable state.
If deployment has the multiple worker for the ``nova-conductor`` and
``nova-scheduler`` service, then new requests are handled by the other workers.

.. important::

     The service manager tracks in-progress tasks and waits only until they
     complete or until :oslo.config:option:`manager_shutdown_timeout` is
     reached, whichever comes first. Operations that do not complete within
     this timeout are still interrupted and can leave instances in an unwanted
     state.

How graceful shutdown works for nova-compute service
----------------------------------------------------

When ``nova-compute`` receives ``SIGTERM``, the following sequence occurs:

#. The primary RPC server (``compute`` topic) stops accepting new requests.
#. The secondary RPC server (``compute-alt`` topic) still active and handles
   the RPC requests needed to finish in-progress tasks.
#. The service manager waits for its tracked in-progress tasks to complete,
   up to :oslo.config:option:`manager_shutdown_timeout` seconds.
#. The secondary RPC server (``compute-alt`` topic) is stopped.
#. The service is stopped.

For ``nova-conductor`` and ``nova-scheduler``, the sequence is the same
except there is only one RPC server and the further requests are handled
by their other workers.

The additional RabbitMQ queue for compute service
-------------------------------------------------

``nova-compute`` service maintains two RPC servers:

* **Primary server** (``compute`` topic): Handles all new incoming requests
  during normal operation. This server is stopped first when a shutdown begins.
* **Secondary server** (``compute-alt`` topic): Receives requests for
  long-running operations that to be continued and completed during shutdown

Because a second RPC server, each compute node will have an additional RabbitMQ
queue named ``compute-alt.<hostname>``.


Operations handled during shutdown
----------------------------------

The following operations which require a sequence of multiple RPC calls use
the secondary RPC server so that they will be allowed to complete during a
graceful shutdown:

* Live migration
* Cold migration
* Revert resize
* Cross-cell resize
* External instance events
* Get console output

When the compute node's RPC version is older than 6.5, Nova automatically falls
back to sending all operations to the primary RPC server. The secondary RPC
server is not used in this case.

Task tracking
-------------

The service manager tracks in-progress tasks and waits only until they finish,
or until the timeout is reached, whichever comes first. Tasks are tracked in
two ways:

* **Synchronous RPC endpoint calls**: Every RPC call dispatched to a
  manager (and to any additional endpoints it registers, such as the
  conductor's compute task manager) is tracked automatically for the
  duration of the call.
* **Long-running background tasks**: Operations that hand off work to a
  background thread and return the RPC worker to the pool, such as
  ``build_instance``, ``snapshot_instance``, live migration, and cold
  migration/resize, are tracked separately for the duration of the
  background operation. Live migration and cold migration/resize involve
  multiple RPC calls across the source and destination compute hosts, so
  these operations remain tracked from the first call until the final call
  that completes or reverts them.

.. note::

   As confirm resize and revert resize are called as a separate operations
   so they are tracked as separate tasks and not part of the cold migration
   or resize operation task tracking.

Tasks are always tracked, but are only logged once a graceful shutdown has
been initiated. When shutdown begins, the manager logs the in-progress
tasks it is waiting on, periodically logs which tasks are still
outstanding, and logs each task as it completes. If the timeout is reached
before all tasks finish, the manager logs the tasks that were still
in-progress at shutdown.

Configuration
-------------

Two configuration options control graceful shutdown behaviour. Both are in the
``[DEFAULT]`` section of ``nova.conf`` of respective service.

.. rubric:: :oslo.config:option:`graceful_shutdown_timeout`

The overall time the service waits before forcefully exit. This is defaults to
180 seconds for each Nova services.

If the service is not exited by this time, the service is stopped
instantaneously. The operators using the external system (e.g. k8s, systemd) to
manage the Nova serviecs should ensure that their service stop timeouts are set
to at least ``graceful_shutdown_timeout`` to avoid forcefully killing service
before Nova finish its graceful shutdown.

.. rubric:: :oslo.config:option:`manager_shutdown_timeout`

This controls how long the service waits for in-progress tasks to finish during
graceful shutdown.

This is defaults to 160 seconds for each service. This must be less than
``graceful_shutdown_timeout``

Setting this option to ``0`` disables the wait entirely: the manager does not
wait for in-progress tasks before proceeding with shutdown.

The operators may want to set the above config options value based on how long
their typical long-running operations (e.g. live migrations) take to complete.

Upgrade considerations
-----------------------

* The default value of ``graceful_shutdown_timeout`` has been raised from 60
  seconds (the ``oslo.service`` default) to 180 seconds for all Nova services.
  If your service manager previously relied on the 60-second default, update
  its stop timeout to at least 180 seconds before upgrading.

* A new option ``manager_shutdown_timeout`` has been added with a default of
  160 seconds. No action is required unless you want to change the value.

* ``nova-compute`` service creates an additional RabbitMQ queue
  (``compute-alt.<hostname>``) on startup. Ensure your message broker has
  capacity for the additional queues.

* During a rolling upgrade where some compute nodes are still running a version
  older than 6.5, Nova will fall back to routing all operations through the
  primary ``compute`` queue. The graceful shutdown feature only works when all
  compute nodes have been upgraded.
