.. -*- rst -*-

=====================
 Keypairs (keypairs)
=====================

Generates, imports, and deletes SSH keys.

List Keypairs
=============

.. rest_method:: GET /v2.1/{tenant_id}/os-keypairs

Lists keypairs that are associated with the account.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
^^^^^^^^

**Example List Keypairs: JSON request**

.. literalinclude:: ../../doc/api_samples/os-keypairs/keypairs-list-resp.json
   :language: javascript

Create Or Import Keypair
========================

.. rest_method:: POST /v2.1/{tenant_id}/os-keypairs

Generates or imports a keypair.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - name: name
  - public_key: public_key

**Example Create Or Import Keypair: JSON request**

.. literalinclude:: ../../doc/api_samples/os-keypairs/keypair-import-req.json
   :language: javascript

Response
^^^^^^^^

**Example Create Or Import Keypair: JSON request**

.. literalinclude:: ../../doc/api_samples/os-keypairs/keypair-import-resp.json
   :language: javascript

Delete Keypair
==============

.. rest_method:: DELETE /v2.1/{tenant_id}/os-keypairs/{keypair_name}

Deletes a keypair.

Normal response codes: 204

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - keypair_name: keypair_name

Response
^^^^^^^^

Show Keypair Details
====================

.. rest_method:: GET /v2.1/{tenant_id}/os-keypairs/{keypair_name}

Shows details for a keypair that is associated with the account.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - keypair_name: keypair_name

Response
^^^^^^^^

**Example Show Keypair Details: JSON request**

.. literalinclude:: ../../doc/api_samples/os-keypairs/keypair-show-resp.json
   :language: javascript

