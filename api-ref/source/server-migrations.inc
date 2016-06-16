.. -*- rst -*-

=========================================
 Server migrations (servers, migrations)
=========================================

List, show, perform actions on and delete server migrations.

List Migrations
===============

.. rest_method:: GET /servers/{server_id}/migrations

Lists in-progress live migrations for a given server.

.. note:: Microversion 2.23 or greater is required for this API.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - migrations: migrations
  - created_at: created
  - dest_compute: migrate_dest_compute
  - dest_host: migrate_dest_host
  - dest_node: migrate_dest_node
  - disk_processed_bytes: migrate_disk_processed_bytes
  - disk_remaining_bytes: migrate_disk_remaining_bytes
  - disk_total_bytes: migrate_disk_total_bytes
  - id: migration_id
  - memory_processed_bytes: migrate_memory_processed_bytes
  - memory_remaining_bytes: migrate_memory_remaining_bytes
  - memory_total_bytes: migrate_memory_total_bytes
  - server_uuid: server_id
  - source_compute: migrate_source_compute
  - source_node: migrate_source_node
  - status: migrate_status
  - updated_at: updated
  - uuid: migration_uuid

**Example List Migrations (2.59)**

.. literalinclude:: ../../doc/api_samples/server-migrations/v2.59/migrations-index.json
   :language: javascript

Show Migration Details
======================

.. rest_method:: GET /servers/{server_id}/migrations/{migration_id}

Show details for an in-progress live migration for a given server.

.. note:: Microversion 2.23 or greater is required for this API.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migration_id: migration_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - migration: migration
  - created_at: created
  - dest_compute: migrate_dest_compute
  - dest_host: migrate_dest_host
  - dest_node: migrate_dest_node
  - disk_processed_bytes: migrate_disk_processed_bytes
  - disk_remaining_bytes: migrate_disk_remaining_bytes
  - disk_total_bytes: migrate_disk_total_bytes
  - id: migration_id
  - memory_processed_bytes: migrate_memory_processed_bytes
  - memory_remaining_bytes: migrate_memory_remaining_bytes
  - memory_total_bytes: migrate_memory_total_bytes
  - server_uuid: server_id
  - source_compute: migrate_source_compute
  - source_node: migrate_source_node
  - status: migrate_status
  - updated_at: updated
  - uuid: migration_uuid

**Example Show Migration Details (2.59)**

.. literalinclude:: ../../doc/api_samples/server-migrations/v2.59/migrations-get.json
   :language: javascript

Force Migration Complete Action (force_complete Action)
=======================================================

.. rest_method:: POST /servers/{server_id}/migrations/{migration_id}/action

Force an in-progress live migration for a given server to complete.

Specify the ``force_complete`` action in the request body.

.. note:: Microversion 2.22 or greater is required for this API.

.. note:: Not all compute back ends support forcefully completing an
    in-progress live migration.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

**Preconditions**

The server OS-EXT-STS:vm_state value must be ``active`` and the server
OS-EXT-STS:task_state value must be ``migrating``.

If the server is locked, you must have administrator privileges to force the
completion of the server migration.

The migration status must be ``running``.

**Asynchronous Postconditions**

After you make this request, you typically must keep polling the server status
to determine whether the request succeeded.

**Troubleshooting**

If the server status remains ``ACTIVE`` for an inordinate amount of time, the
request may have failed. Ensure you meet the preconditions and run the request
again. If the request fails again, investigate the compute back end.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migration_id: migration_id_path
  - force_complete: force_migration_complete

**Example Force Migration Complete (force_complete Action)**

.. literalinclude:: ../../doc/api_samples/server-migrations/force_complete.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST operation.

Delete (Abort) Migration
========================

.. rest_method:: DELETE /servers/{server_id}/migrations/{migration_id}

Abort an in-progress live migration.

.. note:: Microversion 2.24 or greater is required for this API.

.. note:: Not all compute back ends support aborting an in-progress live
    migration.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

**Preconditions**

The server OS-EXT-STS:task_state value must be ``migrating``.

If the server is locked, you must have administrator privileges to force the
completion of the server migration.

The migration status must be ``running``.

**Asynchronous Postconditions**

After you make this request, you typically must keep polling the server status
to determine whether the request succeeded. You may also monitor the migration
using::

    GET /servers/{server_id}/migrations/{migration_id}

**Troubleshooting**

If the server task_state remains ``migrating`` for an inordinate amount of
time, the request may have failed. Ensure you meet the preconditions and run
the request again. If the request fails again, investigate the compute back
end.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migration_id: migration_id_path

Response
--------

There is no body content for the response of a successful DELETE operation.
