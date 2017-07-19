.. -*- rst -*-

=============================
 Server tags (servers, tags)
=============================

Lists tags, creates, replaces or deletes one or more tags for a server, checks
the existence of a tag for a server.

Available since version 2.26

Tags have the following restrictions:

-  Tag is a Unicode bytestring no longer than 60 characters.

-  Tag is a non-empty string.

-  '/' is not allowed to be in a tag name

-  Comma is not allowed to be in a tag name in order to simplify requests that
   specify lists of tags

-  All other characters are allowed to be in a tag name

-  Each server can have up to 50 tags.

List Tags
=========

.. rest_method:: GET /servers/{server_id}/tags

Lists all tags for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - tags: tags

**Example List Tags:**

.. literalinclude:: ../../doc/api_samples/os-server-tags/v2.26/server-tags-index-resp.json
   :language: javascript

Replace Tags
============

.. rest_method:: PUT /servers/{server_id}/tags

Replaces all tags on specified server with the new set of tags.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - tags: tags

**Example Replace Tags:**

.. literalinclude:: ../../doc/api_samples/os-server-tags/v2.26/server-tags-put-all-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - tags: tags

**Example Replace Tags:**

.. literalinclude:: ../../doc/api_samples/os-server-tags/v2.26/server-tags-put-all-resp.json
   :language: javascript

Delete All Tags
===============

.. rest_method:: DELETE /servers/{server_id}/tags

Deletes all tags from the specified server.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

There is no body content for the response of a successful DELETE query

Check Tag Existence
===================

.. rest_method:: GET /servers/{server_id}/tags/{tag}

Checks tag existence on the server. If tag exists response with 204 status code
will be returned. Otherwise returns 404.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - tag: tag

Add a Single Tag
================

.. rest_method:: PUT /servers/{server_id}/tags/{tag}

Adds a single tag to the server if server has no specified tag. Response code
in this case is 201.

If the server has specified tag just returns 204.

Normal response codes: 201, 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - tag: tag

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: tag_location

Delete a Single Tag
===================

.. rest_method:: DELETE /servers/{server_id}/tags/{tag}

Deletes a single tag from the specified server.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - tag: tag

Response
--------

There is no body content for the response of a successful DELETE query
