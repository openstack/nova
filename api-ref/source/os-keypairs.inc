.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=====================
 Keypairs (keypairs)
=====================

Generates, imports, and deletes SSH keys.

List Keypairs
=============

.. rest_method:: GET /os-keypairs

Lists keypairs that are associated with the account.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example List Keypairs: JSON response**

.. literalinclude:: ../../doc/api_samples/keypairs/keypairs-list-resp.json
   :language: javascript

Create Or Import Keypair
========================

.. rest_method:: POST /os-keypairs

Generates or imports a keypair.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - name: name
  - public_key: public_key

**Example Create Or Import Keypair: JSON request**

.. literalinclude:: ../../doc/api_samples/keypairs/keypairs-import-post-req.json
   :language: javascript

Response
--------

**Example Create Or Import Keypair: JSON response**

.. literalinclude:: ../../doc/api_samples/keypairs/keypairs-import-post-resp.json
   :language: javascript

Show Keypair Details
====================

.. rest_method:: GET /os-keypairs/{keypair_name}

Shows details for a keypair that is associated with the account.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - keypair_name: keypair_name

Response
--------

**Example Show Keypair Details: JSON response**

.. literalinclude:: ../../doc/api_samples/keypairs/keypairs-get-resp.json
   :language: javascript

Delete Keypair
==============

.. rest_method:: DELETE /os-keypairs/{keypair_name}

Deletes a keypair.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - keypair_name: keypair_name

Response
--------
