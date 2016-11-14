.. -*- rst -*-
.. needs:example_verification
.. needs:body_verification

=========================================
 Server migrations (servers, migrations)
=========================================

List, show, perform actions on and delete server migrations.

List Migrations
===============

.. rest_method:: GET /servers/{server_id}/migrations

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

**Example List Migrations**

Show Migration Details
======================

.. rest_method:: GET /servers/{server_id}/migrations/{migration_id}

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

**Example Show Migration Details**

Force Migration Complete Action (force_complete Action)
=======================================================

.. rest_method:: POST /servers/{server_id}/migrations/{migration_id}/action

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migration_id: migration_id_path
  - force_complete: force_migration_complete

Response
--------

There is no body content for the response of a successful POST operation.

Delete (Abort) Migration
========================

.. rest_method:: DELETE /servers/{server_id}/migrations/{migration_id}

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - migration_id: migration_id_path

Response
--------

There is no body content for the response of a successful DELETE operation.
