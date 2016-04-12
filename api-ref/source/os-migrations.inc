.. -*- rst -*-

============================
 Migrations (os-migrations)
============================

Shows data on migrations.

List Migrations
===============

.. rest_method:: GET /v2.1/{tenant_id}/os-migrations

Lists in-progress migrations.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
^^^^^^^^

**Example List Migrations: JSON request**

.. literalinclude:: ../../doc/api_samples/os-migrations/migrations-list-resp.json
   :language: javascript

