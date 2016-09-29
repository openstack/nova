.. -*- rst -*-

=========================================
 Migrations (os-migrations) (frozen)
=========================================

Shows data on migrations.

.. warning:: The old top-level resource `/os-migrations` is frozen,
             it won't be extended anymore. Use /servers/{uuid}/migrations instead.

List Migrations
===============

.. rest_method:: GET /os-migrations

Lists in-progress migrations.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - status: migration_status
  - host: migration_host
  - source_compute: migration_source_compute
  - migration_type: migration_type
  - hidden: migration_hidden
  - instance_uuid: migration_instance_uuid

Response
--------

**Example List Migrations: JSON response**

.. literalinclude:: ../../doc/api_samples/os-migrations/migrations-get.json
   :language: javascript

