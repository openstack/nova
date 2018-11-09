.. -*- rst -*-

=========================================
 Migrations (os-migrations)
=========================================

Shows data on migrations.

List Migrations
===============

.. rest_method:: GET /os-migrations

Lists migrations.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

Starting from microversion 2.59, the response is sorted by ``created_at``
and ``id`` in descending order.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - hidden: migration_hidden
  - host: migration_host
  - instance_uuid: migration_instance_uuid
  - migration_type: migration_type
  - source_compute: migration_source_compute
  - status: migration_status
  - limit: migration_limit
  - marker: migration_marker
  - changes-since: changes_since_migration
  - changes-before: changes_before_migration

Response
--------

.. rest_parameters:: parameters.yaml

  - migrations: migrations
  - created_at: created
  - dest_compute: migrate_dest_compute
  - dest_host: migrate_dest_host
  - dest_node: migrate_dest_node
  - id: migration_id
  - instance_uuid: server_id
  - new_instance_type_id: migration_new_flavor_id
  - old_instance_type_id: migration_old_flavor_id
  - source_compute: migrate_source_compute
  - source_node: migrate_source_node
  - status: migrate_status
  - updated_at: updated
  - migration_type: migration_type_2_23
  - links: migration_links_2_23
  - uuid: migration_uuid
  - migrations_links: migration_next_links_2_59

**Example List Migrations: JSON response**

.. literalinclude:: ../../doc/api_samples/os-migrations/migrations-get.json
   :language: javascript

**Example List Migrations (v2.59):**

.. literalinclude:: ../../doc/api_samples/os-migrations/v2.59/migrations-get.json
   :language: javascript

**Example List Migrations With Paging (v2.59):**

.. literalinclude:: ../../doc/api_samples/os-migrations/v2.59/migrations-get-with-limit.json
   :language: javascript

