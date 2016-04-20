.. -*- rst -*-

==========================================================
 Servers - run an administrative action (servers, action)
==========================================================

Enables administrators to perform an action on a server. Specify the
action in the request body.

You can change the administrative password for, create a back up of, and
inject network information into a server.

You can migrate, live-migrate, reset networking on, and reset the state
of a server.

Create Server Back Up (Createbackup Action)
===========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Creates a back up of a server.

Specify the ``createBackup`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - createBackup: createBackup

**Example Create Server Back Up (Createbackup Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-create-backup/create-backup-req.json
   :language: javascript

Response
--------

Inject Network Information (Injectnetworkinfo Action)
=====================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Injects network information into a server.

Specify the ``injectNetworkInfo`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - injectNetworkInfo: injectNetworkInfo

**Example Inject Network Information (Injectnetworkinfo Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-inject-network-info.json
   :language: javascript

Response
--------

Migrate Server (Migrate Action)
===============================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Migrates a server to a host. The scheduler chooses the host.

Specify the ``migrate`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - migrate: migrate

**Example Migrate Server (Migrate Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/migrate-server.json
   :language: javascript

Response
--------

Live-Migrate Server (Os-Migratelive Action)
===========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Live-migrates a server to a new host without rebooting.

Use the ``host`` parameter to specify the destination host. If you omit this parameter, the scheduler chooses a host. If a scheduled host is not suitable, the scheduler tries up to ``migrate_max_retries`` rescheduling attempts.

If both source and destination hosts provide local disks, you can set the ``block_migration`` parameter to ``true``. If either host uses shared storage, the migration fails if you set this parameter to ``true``.

Policy defaults enable only users with the administrative role to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - host: host_migration 
  - block_migration: block_migration
  - disk_over_commit: disk_over_commit

**Example Live-Migrate Server (Os-Migratelive Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/live-migrate-server.json
   :language: javascript

Response
--------

Reset Networking On A Server (Resetnetwork Action)
==================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Resets networking on a server.

Specify the ``resetNetwork`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - resetNetwork: resetNetwork

**Example Reset Networking On A Server (Resetnetwork Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-network.json
   :language: javascript

Response
--------

Reset Server State (Os-Resetstate Action)
=========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Resets the state of a server.

Specify the ``os-resetState`` action and the ``state`` in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-resetState: os-resetState

**Example Reset Server State (Os-Resetstate Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-server-state.json
   :language: javascript

Response
--------

