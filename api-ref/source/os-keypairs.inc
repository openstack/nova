.. -*- rst -*-

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

Request
-------

.. rest_parameters:: parameters.yaml

  - user_id: keypair_user
  - limit: keypair_limit
  - marker: keypair_marker

Response
--------

.. rest_parameters:: parameters.yaml

  - keypairs: keypairs
  - keypair: keypair
  - name: keypair_name
  - public_key: keypair_public_key
  - fingerprint: keypair_fingerprint
  - type: keypair_type
  - keypairs_links: keypair_links

**Example List Keypairs (v2.35): JSON response**

.. literalinclude:: ../../doc/api_samples/os-keypairs/v2.35/keypairs-list-resp.json
   :language: javascript

Create Or Import Keypair
========================

.. rest_method:: POST /os-keypairs

Generates or imports a keypair.

Normal response codes: 200, 201

.. note::

   The success status code was changed from 200 to 201 in version 2.2

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - keypair: keypair
  - name: keypair_name
  - public_key: keypair_public_key_in
  - type: keypair_type_in
  - user_id: keypair_userid_in

**Example Create Or Import Keypair (v2.10): JSON request**

.. literalinclude:: ../../doc/api_samples/os-keypairs/v2.10/keypairs-import-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - keypair: keypair
  - name: keypair_name
  - public_key: keypair_public_key
  - fingerprint: keypair_fingerprint
  - user_id: keypair_userid
  - private_key: keypair_private_key
  - type: keypair_type

**Example Create Or Import Keypair (v2.10): JSON response**

.. literalinclude:: ../../doc/api_samples/os-keypairs/v2.10/keypairs-import-post-resp.json
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

  - keypair_name: keypair_name_path
  - user_id: keypair_user

Response
--------

.. rest_parameters:: parameters.yaml

  - keypair: keypair
  - created_at: created
  - deleted: keypair_deleted
  - deleted_at: keypair_updated_deleted_at
  - fingerprint: keypair_fingerprint
  - id: keypair_id
  - name: keypair_name
  - public_key: keypair_public_key
  - updated_at: keypair_updated_deleted_at
  - user_id: keypair_userid
  - type: keypair_type

**Example Show Keypair Details (v2.10): JSON response**

.. literalinclude:: ../../doc/api_samples/os-keypairs/v2.10/keypairs-get-resp.json
   :language: javascript

Delete Keypair
==============

.. rest_method:: DELETE /os-keypairs/{keypair_name}

Deletes a keypair.

Normal response codes: 202, 204

.. note::

   The normal return code is 204 in version 2.2 to match the fact that
   no body content is returned.

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - keypair_name: keypair_name_path
  - user_id: keypair_user

Response
--------

There is no body content for the response of a successful DELETE query
