.. -*- rst -*-

=====================================
 Server metadata (servers, metadata)
=====================================

Lists metadata, creates or replaces one or more metadata items, and
updates one or more metadata items for a server.

Shows details for, creates or replaces, and updates a metadata item, by
key, for a server.

List All Metadata
=================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/metadata

Lists all metadata for a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
^^^^^^^^

**Example List All Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-list-resp.json
   :language: javascript

Create Or Replace Metadata Items
================================

.. rest_method:: PUT /v2.1/{tenant_id}/servers/{server_id}/metadata

Creates or replaces one or more metadata items for a server.

Creates any metadata items that do not already exist in the server. Removes and completely replaces any metadata items that already exist in the server with the metadata items in the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Create Or Replace Metadata Items: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-create-req.json
   :language: javascript

Response
^^^^^^^^

**Example Create Or Replace Metadata Items: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-list-resp.json
   :language: javascript

Update Metadata Items
=====================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/metadata

Updates one or more metadata items for a server.

Replaces metadata items that match keys. Does not modify items that are not in the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Update Metadata Items: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-create-req.json
   :language: javascript

Response
^^^^^^^^

**Example Update Metadata Items: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-list-resp.json
   :language: javascript

Show Metadata Item Details
==========================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/metadata/{key}

Shows details for a metadata item, by key, for a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - key: key

Response
^^^^^^^^

**Example Show Metadata Item Details: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-show-resp.json
   :language: javascript

Create Or Update Metadata Item
==============================

.. rest_method:: PUT /v2.1/{tenant_id}/servers/{server_id}/metadata/{key}

Creates or replaces a metadata item, by key, for a server.

Creates a metadata item that does not already exist in the server. Removes and completely replaces a metadata item that already exists in the server with the metadata item in the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - key: key

**Example Create Or Update Metadata Item: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-item-update-req.json
   :language: javascript

Response
^^^^^^^^

**Example Create Or Update Metadata Item: JSON request**

.. literalinclude:: ../../doc/api_samples/metadata/server-metadata-item-show-resp.json
   :language: javascript

Delete Metadata Item
====================

.. rest_method:: DELETE /v2.1/{tenant_id}/servers/{server_id}/metadata/{key}

Deletes a metadata item, by key, from a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 204

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - key: key

Response
^^^^^^^^

