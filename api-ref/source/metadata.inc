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

.. rest_method:: GET /servers/{server_id}/metadata

Lists all metadata for a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - metadata: metadata_object

**Example List All Metadata**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-all-resp.json
   :language: javascript

Create or Update Metadata Items
===============================

.. rest_method:: POST /servers/{server_id}/metadata

Create or update one or more metadata items for a server.

Creates any metadata items that do not already exist in the server, replaces
exists metadata items that match keys. Does not modify items that are not in
the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - metadata: metadata_object

**Example Update Metadata Items**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-all-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - metadata: metadata_object

**Example Update Metadata Items**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-all-resp.json
   :language: javascript

Replace Metadata Items
======================

.. rest_method:: PUT /servers/{server_id}/metadata

Replaces one or more metadata items for a server.

Creates any metadata items that do not already exist in the server. Removes and completely replaces any metadata items that already exist in the server with the metadata items in the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - metadata: metadata_object

**Example Create Or Replace Metadata Items**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-all-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - metadata: metadata_object

**Example Create Or Replace Metadata Items**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-all-resp.json
   :language: javascript

Show Metadata Item Details
==========================

.. rest_method:: GET /servers/{server_id}/metadata/{key}

Shows details for a metadata item, by key, for a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - key: key

Response
--------

.. rest_parameters:: parameters.yaml

  - meta: metadata_object

**Example Show Metadata Item Details**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-resp.json
   :language: javascript

Create Or Update Metadata Item
==============================

.. rest_method:: PUT /servers/{server_id}/metadata/{key}

Creates or replaces a metadata item, by key, for a server.

Creates a metadata item that does not already exist in the server. Replaces
existing metadata items that match keys with the metadata item in the request.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - key: key

**Example Create Or Update Metadata Item**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - meta: metadata_object

**Example Create Or Update Metadata Item**

.. literalinclude:: ../../doc/api_samples/server-metadata/server-metadata-resp.json
   :language: javascript

Delete Metadata Item
====================

.. rest_method:: DELETE /servers/{server_id}/metadata/{key}

Deletes a metadata item, by key, from a server.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - key: key

Response
--------

If successful, this method does not return content in the response body.
