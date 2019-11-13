.. -*- rst -*-

==========================================================
 Servers - run an administrative action (servers, action)
==========================================================

Enables administrators to perform an action on a server. Specify the
action in the request body.

You can inject network information into, migrate, live-migrate,
reset networking on, reset the state of a server,
and evacuate a server from a failed host to a new host.


Inject Network Information (injectNetworkInfo Action)
=====================================================

.. rest_method:: POST /servers/{server_id}/action

Injects network information into a server.

Specify the ``injectNetworkInfo`` action in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

.. warning:: There is very limited support on this API, For more information,
             see `nova virt support matrix
             <https://docs.openstack.org/nova/latest/user/support-matrix.html>`__

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - injectNetworkInfo: injectNetworkInfo

**Example Inject Network Information (injectNetworkInfo Action)**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-inject-network-info.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Migrate Server (migrate Action)
===============================

.. rest_method:: POST /servers/{server_id}/action

Migrates a server to a host.

Specify the ``migrate`` action in the request body.

Up to microversion 2.55, the scheduler chooses the host.
Starting from microversion 2.56, the ``host`` parameter is available
to specify the destination host. If you specify ``null`` or don't specify
this parameter, the scheduler chooses a host.

**Asynchronous Postconditions**

A successfully migrated server shows a ``VERIFY_RESIZE`` status and ``finished``
migration status. If the cloud has configured the `resize_confirm_window`_
option of the Compute service to a positive value, the Compute service
automatically confirms the migrate operation after the configured interval.

.. _resize_confirm_window: https://docs.openstack.org/nova/latest/configuration/config.html#DEFAULT.resize_confirm_window

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403)
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migrate: migrate
  - host: host_migration_2_56

**Example Migrate Server (migrate Action) (v2.1)**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/migrate-server.json
   :language: javascript

**Example Migrate Server (migrate Action) (v2.56)**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/v2.56/migrate-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Live-Migrate Server (os-migrateLive Action)
===========================================

.. rest_method:: POST /servers/{server_id}/action

Live-migrates a server to a new host without rebooting.

Specify the ``os-migrateLive`` action in the request body.

Use the ``host`` parameter to specify the destination host. If
this param is ``null``, the scheduler chooses a host. If a scheduled host
is not suitable to do migration, the scheduler tries up to
``migrate_max_retries`` rescheduling attempts.

Starting from API version 2.25, the ``block_migration`` parameter could be
to ``auto`` so that nova can decide value of block_migration during live
migration.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Starting from REST API version 2.34 pre-live-migration checks are done
asynchronously, results of these checks are available in ``instance-actions``.
Nova responds immediately, and no pre-live-migration checks are returned.
The instance will not immediately change state to ``ERROR``, if a failure of
the live-migration checks occurs.

Starting from API version 2.68, the ``force`` parameter is no longer accepted
as this could not be meaningfully supported by servers with complex resource
allocations.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403)
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - os-migrateLive: os-migrateLive
  - host: host_migration
  - block_migration: block_migration
  - block_migration: block_migration_2_25
  - disk_over_commit: disk_over_commit
  - force: force_live_migrate

**Example Live-Migrate Server (os-migrateLive Action)**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/v2.30/live-migrate-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Reset Networking On A Server (resetNetwork Action)
==================================================

.. rest_method:: POST /servers/{server_id}/action

Resets networking on a server.

.. note::

    Only the XenServer driver implements this feature and only if the guest
    has the XenAPI agent in the targeted server.

Specify the ``resetNetwork`` action in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - resetNetwork: resetNetwork

**Example Reset Networking On A Server (resetNetwork Action)**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-network.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.

.. _os-resetState:

Reset Server State (os-resetState Action)
=========================================

.. rest_method:: POST /servers/{server_id}/action

Resets the state of a server.

Specify the ``os-resetState`` action and the ``state`` in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - os-resetState: os-resetState
  - os-resetState.state: os-resetState_state

**Example Reset Server State (os-resetState Action)**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-server-state.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.
